"""Integrations: settings, the WhatsApp webhook, email intake and the agent.

The agent runs for real -- LangChain's ReAct loop calling the real tools over
the real services -- with a scripted chat model standing in for Claude, so no
API key or network is needed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal as D
from typing import Any, Callable, List

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import text

from app.config import get_settings
from app.services import email_inbox, inbound

PHONE_ID = "1098765432"
VERIFY = "aec-verify-123"


class ScriptedModel(BaseChatModel):
    """A chat model that plays a fixed script of turns, one per call."""

    script: List[Any]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: List[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        step = self.script.pop(0)
        message = step(messages) if callable(step) else step
        return ChatResult(generations=[ChatGeneration(message=message)])


def call(name: str, args: Callable[[List[BaseMessage]], dict] | dict, call_id: str) -> Callable:
    def step(messages):
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": args(messages) if callable(args) else args, "id": call_id,
        }])
    return step


def last_result(messages: List[BaseMessage]) -> Any:
    return json.loads([m for m in messages if isinstance(m, ToolMessage)][-1].content)


@pytest.fixture(autouse=True)
def server_ai_credentials(monkeypatch):
    """The server holds Gemini credentials, as it does in production."""
    monkeypatch.setattr(get_settings(), "vertex_api_key", "server-side-test-key")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")


@pytest.fixture()
def wired(session_factory, monkeypatch):
    """Background work uses the test schema, and the model is scripted."""
    monkeypatch.setattr(inbound, "session_factory", session_factory)
    scripts: List[List[Any]] = []
    monkeypatch.setattr(inbound, "model_factory", lambda model: ScriptedModel(script=scripts.pop(0)))
    return scripts


def enable_ai(client):
    response = client.put("/api/integrations/ai", json={"enabled": True})
    assert response.status_code == 200, response.text


def enable_whatsapp(client, app_secret=None):
    body = {"enabled": True, "config": {"phone_number_id": PHONE_ID, "verify_token": VERIFY,
                                        "business_account_id": "WABA-1"}}
    if app_secret:
        body["credentials"] = {"app_secret": app_secret}
    response = client.put("/api/integrations/whatsapp", json=body)
    assert response.status_code == 200, response.text


def whatsapp_payload(message_id="wamid.1", sender="919876543210", body="Need 40 bags of cement, rate?"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA-1", "changes": [{
        "field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550001111", "phone_number_id": PHONE_ID},
            "contacts": [{"profile": {"name": "Ravi Builders"}, "wa_id": sender}],
            "messages": [{"from": sender, "id": message_id, "timestamp": "1762500000",
                          "type": "text", "text": {"body": body}}],
        }}]}]}


# --- settings -----------------------------------------------------------------------


EMAIL = {"imap_host": "imap.test", "imap_port": 993, "username": "sales@aec.test"}


def test_the_ai_has_no_credentials_for_users_to_see_or_set(client):
    data = client.get("/api/integrations").json()
    assert data["ai"]["credentials"] == {}
    assert "server-side-test-key" not in client.get("/api/integrations").text
    # Only models the server has credentials for, cheapest Gemini first.
    assert [model["id"] for model in data["models"]][0] == "gemini-3.1-flash-lite"
    assert all(model["provider"] == "vertex" for model in data["models"])
    assert data["providers"] == ["Google Gemini (Vertex AI)"]
    assert data["ai"]["config"]["model"] == "gemini-3.1-flash-lite"
    # A credential cannot be sent in either.
    response = client.put("/api/integrations/ai", json={"credentials": {"api_key": "sk-x"}})
    assert response.status_code == 422


def test_users_switch_the_ai_on_and_choose_a_model(client):
    response = client.put("/api/integrations/ai", json={"enabled": True, "config": {"model": "gemini-3.8-flash"}})
    assert response.status_code == 200
    assert response.json()["enabled"] is True and response.json()["config"]["model"] == "gemini-3.8-flash"
    # A model whose provider has no credentials on the server is refused.
    response = client.put("/api/integrations/ai", json={"config": {"model": "claude-opus-5-5"}})
    assert response.status_code == 422


def test_without_server_credentials_the_ai_cannot_be_switched_on(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "vertex_api_key", "")
    monkeypatch.setattr(get_settings(), "vertex_project", "")
    assert client.get("/api/integrations").json()["models"] == []
    response = client.put("/api/integrations/ai", json={"enabled": True})
    assert response.status_code == 422
    assert "not set up on the server" in response.json()["message"]


def test_an_integration_cannot_be_switched_on_half_configured(client):
    response = client.put("/api/integrations/whatsapp", json={"enabled": True})
    assert response.status_code == 422
    assert "phone number ID" in response.json()["message"]


def test_user_entered_credentials_are_encrypted_and_never_returned(client, db):
    response = client.put("/api/integrations/email", json={
        "enabled": True, "config": EMAIL, "credentials": {"password": "imap-secret-9876"},
    })
    assert response.status_code == 200, response.text
    assert "imap-secret-9876" not in client.get("/api/integrations").text
    assert client.get("/api/integrations").json()["email"]["credentials"]["password"] == {"set": True, "hint": "…9876"}
    stored = db.execute(text("SELECT secrets FROM integration_settings WHERE name = 'email'")).scalar_one()
    assert "imap-secret-9876" not in stored


def test_an_omitted_credential_is_kept_and_an_empty_one_removed(client):
    client.put("/api/integrations/email", json={
        "enabled": True, "config": EMAIL, "credentials": {"password": "imap-secret-9876"},
    })
    client.put("/api/integrations/email", json={"config": {"folder": "Sales"}})
    email = client.get("/api/integrations").json()["email"]
    assert email["config"]["folder"] == "Sales" and email["credentials"]["password"]["set"] is True
    # Removing the password of a switched-on integration is refused ...
    assert client.put("/api/integrations/email", json={"credentials": {"password": ""}}).status_code == 422
    # ... but allowed once it is off.
    response = client.put("/api/integrations/email", json={"enabled": False, "credentials": {"password": ""}})
    assert response.json()["credentials"]["password"]["set"] is False


# --- WhatsApp webhook -------------------------------------------------------------


def test_meta_verification_echoes_the_challenge_only_with_the_right_token(client):
    enable_whatsapp(client)
    params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "8812"}
    ok = client.get("/api/integrations/whatsapp/webhook", params=params)
    assert ok.status_code == 200 and ok.text == "8812"
    bad = client.get("/api/integrations/whatsapp/webhook", params={**params, "hub.verify_token": "nope"})
    assert bad.status_code == 403


def test_a_whatsapp_enquiry_becomes_an_enquiry(client, wired, make_product):
    cement = make_product("Cement, 50kg bag", sku="CEM-50", mrp="380.00")
    make_product("Steel rod, 12mm", sku="STL-12", mrp="520.00")
    enable_ai(client)
    enable_whatsapp(client)
    wired.append([
        call("find_customers", {"query": "9876543210"}, "c1"),
        call("create_customer", {"name": "Ravi Builders", "phone": "+919876543210"}, "c2"),
        call("search_products", {"query": "cement"}, "c3"),
        call("create_enquiry", lambda messages: {
            "customer_id": json.loads([m for m in messages if isinstance(m, ToolMessage)][1].content)["id"],
            "lines": [{"product_id": last_result(messages)[0]["id"], "quantity": 40}],
            "notes": "40 bags of cement, asked for the rate.",
        }, "c4"),
        AIMessage(content="ENQUIRY: 40 bags of cement for Ravi Builders."),
    ])

    response = client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload())
    assert response.status_code == 200 and response.json() == {"received": 1}

    message = client.get("/api/integrations/messages").json()["items"][0]
    assert message["status"] == "enquiry_created", message
    assert message["sender"] == "+919876543210"
    assert message["summary"] == "40 bags of cement for Ravi Builders."

    enquiry = client.get("/api/enquiries/{}".format(message["enquiry_id"])).json()
    assert enquiry["source"] == "whatsapp" and enquiry["source_detail"] == "+919876543210"
    assert enquiry["customer"]["name"] == "Ravi Builders"
    assert [(i["product_id"], D(i["quantity"])) for i in enquiry["items"]] == [(str(cement.id), D(40))]
    # Priced from the product master, exactly as a typed-in enquiry is.
    assert D(enquiry["total_amount"]) == D("15200.00")


def test_a_message_that_is_not_an_enquiry_records_nothing(client, wired):
    enable_ai(client)
    enable_whatsapp(client)
    wired.append([AIMessage(content="NOT_ENQUIRY: asking when yesterday's delivery will arrive.")])
    client.post("/api/integrations/whatsapp/webhook",
                json=whatsapp_payload(body="When will yesterday's truck arrive?"))
    message = client.get("/api/integrations/messages").json()["items"][0]
    assert message["status"] == "not_enquiry"
    assert message["enquiry_id"] is None
    assert client.get("/api/enquiries").json()["total"] == 0


def test_a_repeat_delivery_from_meta_is_processed_once(client, wired):
    enable_ai(client)
    enable_whatsapp(client)
    wired.append([AIMessage(content="NOT_ENQUIRY: greeting.")])
    first = client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(body="Hi"))
    again = client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(body="Hi"))
    assert first.json() == {"received": 1} and again.json() == {"received": 0}
    assert client.get("/api/integrations/messages").json()["total"] == 1


def test_with_an_app_secret_only_signed_posts_are_accepted(client, wired):
    enable_ai(client)
    enable_whatsapp(client, app_secret="meta-app-secret")
    raw = json.dumps(whatsapp_payload(body="Hello")).encode()
    unsigned = client.post("/api/integrations/whatsapp/webhook", content=raw,
                           headers={"Content-Type": "application/json"})
    assert unsigned.status_code == 403

    wired.append([AIMessage(content="NOT_ENQUIRY: greeting.")])
    signature = "sha256=" + hmac.new(b"meta-app-secret", raw, hashlib.sha256).hexdigest()
    signed = client.post("/api/integrations/whatsapp/webhook", content=raw,
                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature})
    assert signed.status_code == 200 and signed.json() == {"received": 1}


def test_messages_wait_as_skipped_when_ai_is_off_and_can_be_retried(client, wired):
    enable_whatsapp(client)
    client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(body="Rate for cement?"))
    message = client.get("/api/integrations/messages").json()["items"][0]
    assert message["status"] == "skipped"

    enable_ai(client)
    wired.append([AIMessage(content="NO_MATCH: cement is not in the catalogue.")])
    retried = client.post("/api/integrations/messages/{}/retry".format(message["id"]))
    assert retried.status_code == 200
    assert client.get("/api/integrations/messages").json()["items"][0]["status"] == "no_match"


# --- email --------------------------------------------------------------------------


RAW_EMAIL = (
    b"From: Asha Traders <asha@traders.test>\r\n"
    b"To: sales@aec.test\r\n"
    b"Subject: Quotation needed\r\n"
    b"Message-ID: <q-123@traders.test>\r\n"
    b"Date: Fri, 06 Nov 2026 10:00:00 +0530\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"Please quote for 25 steel rods 12mm.\r\n"
)


class FakeImap:
    def __init__(self, messages):
        self.messages = messages
        self.seen = []

    def login(self, user, password):
        assert password == "imap-pass"

    def select(self, folder):
        return "OK", [b"1"]

    def search(self, charset, criterion):
        return "OK", [b" ".join(str(n).encode() for n in range(1, len(self.messages) + 1))]

    def fetch(self, number, parts):
        return "OK", [(b"1 (BODY[] {123}", self.messages[int(number) - 1]), b")"]

    def store(self, number, flags, value):
        self.seen.append(number)

    def logout(self):
        pass


def test_email_is_parsed_into_sender_subject_and_text():
    fields = email_inbox.parse_email(RAW_EMAIL)
    assert fields["external_id"] == "<q-123@traders.test>"
    assert fields["sender"] == "asha@traders.test" and fields["sender_name"] == "Asha Traders"
    assert fields["subject"] == "Quotation needed"
    assert fields["body"] == "Please quote for 25 steel rods 12mm."


def test_check_now_reads_unread_mail_once_and_marks_it_read(client, wired, monkeypatch):
    fake = FakeImap([RAW_EMAIL])
    monkeypatch.setattr(email_inbox, "imap_factory", lambda host, port: fake)
    enable_ai(client)
    response = client.put("/api/integrations/email", json={
        "enabled": True,
        "config": {"imap_host": "imap.test", "imap_port": 993, "username": "sales@aec.test"},
        "credentials": {"password": "imap-pass"},
    })
    assert response.status_code == 200, response.text

    wired.append([AIMessage(content="NO_MATCH: steel rods are not in the catalogue.")])
    assert client.post("/api/integrations/email/check").json() == {"new_messages": 1}
    assert fake.seen == [b"1"]
    message = client.get("/api/integrations/messages", params={"channel": "email"}).json()["items"][0]
    assert message["subject"] == "Quotation needed" and message["status"] == "no_match"

    # The same mail read again (say, marked unread by hand) is not processed twice.
    assert client.post("/api/integrations/email/check").json() == {"new_messages": 0}
    email = client.get("/api/integrations").json()["email"]
    assert email["config"]["last_checked_at"] and email["config"]["last_error"] is None
    assert email["credentials"]["password"] == {"set": True, "hint": "…pass"}
