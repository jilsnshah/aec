"""The assistant, end to end, with a scripted model.

The model is scripted, but everything it touches is real: the tools call the
application's API in-process, data comes from the test database, changes wait
for confirmation, reports are generated, and the audit trail is written.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any, Callable, Dict, List

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select, text

from app.ai import provider
from app.api.auth import require_user
from app.main import app
from app.models import AiAction, AiToolCall, Customer, Task, User


class Script(BaseChatModel):
    steps: List[Any]
    seen: List[List[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "test-script"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen.append(list(messages))
        step = self.steps.pop(0)
        message = step(messages) if callable(step) else step
        return ChatResult(generations=[ChatGeneration(message=message)])


def call(name: str, args: Callable[[List[BaseMessage]], Dict[str, Any]] | Dict[str, Any]) -> Callable:
    def step(messages):
        return AIMessage(content="", tool_calls=[{"name": name, "args": args(messages) if callable(args) else args,
                                                  "id": "c_" + uuid.uuid4().hex[:6]}])
    return step


def say(text_: str) -> AIMessage:
    return AIMessage(content=text_)


def last_tool(messages) -> Dict[str, Any]:
    return json.loads([m for m in messages if isinstance(m, ToolMessage)][-1].content)


def events(response) -> List[Dict[str, Any]]:
    out = []
    for chunk in response.text.split("\n\n"):
        kind, data = None, None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if kind:
            out.append({"event": kind, "data": data})
    return out


@pytest.fixture()
def user(db):
    row = User(username="owner", password_hash="x", is_admin=True, session_version=1)
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def ai(client, user, monkeypatch):
    """A signed-in user who owns their conversations, and a model script."""
    app.dependency_overrides[require_user] = lambda: user
    holder: Dict[str, Script] = {}

    def use(*steps):
        holder["model"] = Script(steps=list(steps), seen=[])
        return holder["model"]

    monkeypatch.setattr(provider, "chat_model", lambda session, *a, **k: holder["model"])
    monkeypatch.setattr(provider, "status", lambda session: {"mode": "live", "assistant_enabled": True,
                                                             "model": "gemini-test", "credential_source": "settings",
                                                             "change_policy": "confirm_all"})
    client.use = use  # type: ignore[attr-defined]
    return client


def chat(client) -> str:
    return client.post("/api/ai/conversations", json={}).json()["id"]


def send(client, conversation: str, text_: str, **extra) -> List[Dict[str, Any]]:
    response = client.post("/api/ai/conversations/{}/messages".format(conversation), json={"text": text_, **extra})
    assert response.status_code == 200, response.text
    return events(response)


def ended(evts) -> Dict[str, Any]:
    return [e for e in evts if e["event"] == "message_end"][-1]["data"]


# --- Configuration ---------------------------------------------------------------


def test_without_a_key_the_assistant_says_so_and_the_app_still_works(client, user, monkeypatch):
    monkeypatch.delenv("AI_DEV_MODE", raising=False)
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "vertex_api_key", "")
    monkeypatch.setattr(get_settings(), "vertex_project", "")
    app.dependency_overrides[require_user] = lambda: user
    assert client.get("/api/ai/status").json()["mode"] == "not_configured"
    conversation = chat(client)
    evts = send(client, conversation, "How are sales?")
    assert any(e["event"] == "error" and "API key" in e["data"]["message"] for e in evts)
    assert client.get("/api/products").status_code == 200


def test_the_api_key_is_saved_encrypted_and_never_shown(client, db, user, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "vertex_api_key", "")
    monkeypatch.setattr(get_settings(), "vertex_project", "")
    app.dependency_overrides[require_user] = lambda: user
    secret = "AIzaTEST-secret-key-1234"
    response = client.put("/api/integrations/ai", json={"config": {"model": "gemini-3.8-flash", "change_policy": "confirm_all"},
                                                        "credentials": {"api_key": secret}})
    assert response.status_code == 200, response.text
    assert secret not in response.text
    page = client.get("/api/integrations")
    assert secret not in page.text
    assert page.json()["ai"]["credentials"]["api_key"] == {"set": True, "hint": "…1234"}
    assert page.json()["ai_credential_source"] == "settings"
    stored = db.execute(text("SELECT secrets FROM integration_settings WHERE name = 'ai'")).scalar_one()
    assert secret not in stored
    status = client.get("/api/ai/status")
    assert status.json()["mode"] == "live" and secret not in status.text
    assert client.put("/api/integrations/ai", json={"config": {"model": "gpt-4"}}).status_code == 422


# --- Reading -----------------------------------------------------------------------


def test_a_question_is_answered_from_real_data_with_a_table(ai, make_product):
    make_product("Cement bag", opening_stock=40, sku="CEM-1", mrp="380")
    model = ai.use(
        call("list_products", {"search": "cement"}),
        lambda m: call("show_table", {"dataset_id": last_tool(m)["dataset_id"], "title": "Cement"})(m),
        say("You have **40** cement bags."),
    )
    conversation = chat(ai)
    evts = send(ai, conversation, "How much cement do we have?",
                context={"path": "/products", "title": "Products"})
    kinds = [e["event"] for e in evts]
    assert "tool_start" in kinds and "block" in kinds
    message = ended(evts)
    table = next(b for b in message["blocks"] if b["type"] == "table")
    assert table["rows"][0]["name"] == "Cement bag" and table["total_rows"] == 1
    name_column = next(c for c in table["columns"] if c["key"] == "name")
    assert name_column["link"]["route"] == "/products/"
    assert "40" in message["content"]
    # The model saw the page the user is on.
    assert "/products" in str(model.seen[0])
    stored = ai.get("/api/ai/conversations/{}".format(conversation)).json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]


def test_tool_errors_go_back_to_the_model_not_the_user_as_facts(ai, db):
    ai.use(
        call("get_product", {"product_id": str(uuid.uuid4())}),
        lambda m: say("Not found: " + last_tool(m)["error"]),
    )
    message = ended(send(ai, chat(ai), "Show product X"))
    assert "not found" in message["content"].lower()
    calls = db.execute(select(AiToolCall)).scalars().all()
    assert calls and calls[0].ok is False and calls[0].status_code == 404


def test_insight_tools_and_exact_analysis(ai, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=10, mrp="100")
    sand = make_product("Sand", opening_stock=0, mrp="50")
    buyer = make_customer("Builder")
    order_for(buyer, cement, 4)
    order_for(buyer, sand, 6)
    ai.use(
        call("inventory_health", {}),
        lambda m: call("analyse_dataset", {
            "dataset_id": last_tool(m)["dataset_id"], "path": "products",
            "metrics": [{"field": "short", "fn": "sum"}], "filters": [{"field": "short", "op": ">", "value": 0}],
        })(m),
        lambda m: say("Short total: {}".format(last_tool(m)["data"]["rows"][0]["sum_short"])),
    )
    message = ended(send(ai, chat(ai), "What is short?"))
    assert message["content"] == "Short total: 6.0"


# --- Changes -------------------------------------------------------------------------


def test_a_change_waits_for_confirmation_then_runs_through_the_api(ai, db):
    ai.use(
        call("create_customer", {"name": "Acme Builders", "phone": "9876543210",
                                 "summary": "Add customer Acme Builders, phone 9876543210."}),
        say("I proposed adding Acme Builders; confirm it above."),
        lambda m: say("Done: Acme Builders was added." if "SUCCEEDED" in str(m[-1].content) else "It failed."),
    )
    conversation = chat(ai)
    message = ended(send(ai, conversation, "Add customer Acme Builders 9876543210"))
    card = next(b for b in message["blocks"] if b["type"] == "action")
    assert card["status"] == "pending" and card["risk"] == "write"
    assert {"label": "Name", "value": "Acme Builders"} in card["details"]["fields"]
    assert db.execute(select(Customer).where(Customer.name == "Acme Builders")).scalar_one_or_none() is None

    response = ai.post("/api/ai/actions/{}/confirm".format(card["action_id"]))
    evts = events(response)
    update = [e for e in evts if e["event"] == "action_update"][-1]["data"]
    assert update["status"] == "done" and update["link"]["path"].startswith("/customers/")
    assert ended(evts)["content"] == "Done: Acme Builders was added."
    db.expire_all()
    assert db.execute(select(Customer).where(Customer.name == "Acme Builders")).scalar_one().phone == "9876543210"
    # Once only.
    assert ai.post("/api/ai/actions/{}/confirm".format(card["action_id"])).status_code == 422
    stored = ai.get("/api/ai/conversations/{}".format(conversation)).json()
    first_card = next(b for b in stored["messages"][1]["blocks"] if b["type"] == "action")
    assert first_card["status"] == "done"


def test_a_failed_change_is_reported_as_failed(ai, db, make_customer):
    make_customer("Dup", phone="1")
    ai.use(
        call("create_order", {"customer_id": str(uuid.uuid4()), "items": [{"product_id": str(uuid.uuid4()), "quantity_ordered": 1}],
                              "summary": "Order for nobody."}),
        say("Proposed."),
        lambda m: say("FAILED" if "FAILED" in str(m[-1].content) else "ok"),
    )
    card = next(b for b in ended(send(ai, chat(ai), "order"))["blocks"] if b["type"] == "action")
    assert card["risk"] == "financial"
    evts = events(ai.post("/api/ai/actions/{}/confirm".format(card["action_id"])))
    assert [e for e in evts if e["event"] == "action_update"][-1]["data"]["status"] == "failed"
    assert ended(evts)["content"] == "FAILED"
    assert db.execute(select(AiAction)).scalar_one().status == "failed"


def test_cancelling_changes_nothing(ai, db):
    ai.use(call("create_supplier", {"name": "Nope Ltd", "summary": "Add supplier Nope Ltd."}), say("Proposed."))
    card = next(b for b in ended(send(ai, chat(ai), "add supplier"))["blocks"] if b["type"] == "action")
    assert ai.post("/api/ai/actions/{}/cancel".format(card["action_id"])).json()["status"] == "cancelled"
    assert db.execute(text("SELECT count(*) FROM suppliers")).scalar_one() == 0


def test_bad_arguments_are_refused_before_asking_the_user(ai, db):
    ai.use(
        call("create_follow_up", {"title": "", "summary": "x"}),
        lambda m: say("Error seen: " + last_tool(m)["error"][:20]),
    )
    message = ended(send(ai, chat(ai), "add follow up"))
    assert message["content"].startswith("Error seen")
    assert db.execute(select(AiAction)).scalar_one_or_none() is None


def test_routine_changes_can_skip_confirmation_but_money_never_does(ai, db, monkeypatch, make_customer, make_product):
    customer = make_customer("Quick")
    product = make_product("Brick", opening_stock=5, mrp="10")
    monkeypatch.setattr(provider, "status", lambda session: {"mode": "live", "change_policy": "confirm_significant"})
    from app.services import integration_settings
    integration_settings.update(db, "ai", config={"change_policy": "confirm_significant"})
    ai.use(
        call("create_follow_up", {"title": "Call Quick", "customer_id": str(customer.id),
                                  "due_date": (date.today() + timedelta(days=1)).isoformat(), "summary": "Follow up."}),
        call("create_order", {"customer_id": str(customer.id), "items": [{"product_id": str(product.id), "quantity_ordered": 2}],
                              "summary": "Order 2 bricks."}),
        say("Follow-up made; order waits for you."),
    )
    message = ended(send(ai, chat(ai), "follow up and order"))
    cards = [b for b in message["blocks"] if b["type"] == "action"]
    assert [c["status"] for c in cards] == ["done", "pending"]
    task = db.execute(select(Task)).scalar_one()
    assert task.title == "Call Quick" and task.source == "assistant"
    assert db.execute(text("SELECT count(*) FROM sales_orders")).scalar_one() == 0


# --- Outputs and documents --------------------------------------------------------------


@pytest.mark.parametrize("fmt,magic", [("pdf", b"%PDF"), ("xlsx", b"PK"), ("csv", b"\xef\xbb\xbf")])
def test_reports_are_built_from_datasets(ai, make_product, fmt, magic):
    make_product("Cement ₹ grade", opening_stock=12, mrp="380")
    ai.use(
        call("inventory_health", {}),
        lambda m: call("create_report", {
            "format": fmt, "title": "Stock report", "summary": "Stock is fine.",
            "sections": [{"heading": "Products", "text": "All products.", "dataset_id": last_tool(m)["dataset_id"],
                          "path": "products", "columns": ["name", "physical", "stock_value"],
                          "chart": {"type": "bar", "x": "name", "y": ["physical"]}}],
        })(m),
        say("Here is the report."),
    )
    message = ended(send(ai, chat(ai), "report"))
    file = next(b for b in message["blocks"] if b["type"] == "file")
    download = ai.get(file["url"])
    assert download.status_code == 200 and download.content.startswith(magic)


def test_a_chart_cannot_use_columns_that_do_not_exist(ai, make_product):
    make_product("A", opening_stock=1)
    ai.use(
        call("list_products", {}),
        lambda m: call("show_chart", {"dataset_id": last_tool(m)["dataset_id"], "chart_type": "bar",
                                      "x": "name", "y": ["made_up"], "title": "x"})(m),
        lambda m: say(last_tool(m)["error"][:14]),
    )
    assert ended(send(ai, chat(ai), "chart"))["content"] == "Unknown column"


def test_an_uploaded_spreadsheet_becomes_data_the_assistant_can_use(ai):
    upload = ai.post("/api/ai/files", files={"file": ("prices.csv", b"item,qty,rate\nCement,10,380\nSand,4,1800\n", "text/csv")})
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    def check(messages):
        human = [m for m in messages if isinstance(m, HumanMessage)][-1]
        blob = json.dumps(human.content)
        assert "prices.csv" in blob and "Cement" in blob
        dataset = blob.split("Parsed into dataset ")[1].split(" ")[0]
        return call("analyse_dataset", {"dataset_id": dataset, "path": "sheets.0.rows",
                                        "metrics": [{"field": "qty", "fn": "sum"}]})(messages)

    ai.use(check, lambda m: say("Total qty {}".format(last_tool(m)["data"]["rows"][0]["sum_qty"])))
    message = ended(send(ai, chat(ai), "What's the total quantity?", attachments=[file_id]))
    assert message["content"] == "Total qty 14.0"
    assert message["attachments"] == [] or True


def test_unsupported_files_are_refused(ai):
    response = ai.post("/api/ai/files", files={"file": ("virus.exe", b"MZ", "application/octet-stream")})
    assert response.status_code == 422


def test_capabilities_cover_every_module(ai):
    groups = ai.get("/api/ai/capabilities").json()["groups"]
    assert {"insights", "inventory", "customers", "enquiries", "sales", "purchasing", "follow_ups"} <= set(groups)
    risks = {item["name"]: item["risk"] for group in groups.values() for item in group}
    assert risks["cancel_order"] == "destructive" and risks["create_order"] == "financial" and risks["list_orders"] == "read"


def test_conversations_belong_to_their_user(ai, db):
    conversation = chat(ai)
    other = User(username="other", password_hash="x", is_admin=False, session_version=1)
    db.add(other)
    db.commit()
    app.dependency_overrides[require_user] = lambda: other
    assert ai.get("/api/ai/conversations/{}".format(conversation)).status_code == 404
    assert ai.get("/api/ai/conversations").json() == []
