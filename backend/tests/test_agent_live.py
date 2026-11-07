"""Live evaluation of the enquiry agent against a real model.

Each case posts a WhatsApp webhook -- exactly what Meta sends -- carrying a
customer's message, and checks what the agent recorded. The messages are
deliberately loose: Hinglish, Gujarati mixed in, trade slang ("bori", "saria",
"reti", "thela"), and product names that never match the catalogue word for
word. A few messages are not enquiries at all.

These call a paid model API, so they only run when a key is set:

    ANTHROPIC_API_KEY=... pytest tests/test_agent_live.py -v -s        # Claude, as the app uses
    GEMINI_API_KEY=...    pytest tests/test_agent_live.py -v -s        # Gemini, for comparison
    VERTEX_PROJECT=...    pytest tests/test_agent_live.py -v -s        # Gemini on Vertex AI (ADC)
    LIVE_MODEL=...        overrides the model id

The same agent, prompt and tools run either way; only the chat model changes.
"""
from __future__ import annotations

import os
from decimal import Decimal as D
from typing import Dict, List, Optional, Tuple

import pytest

from app.services import ai_agent, inbound

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
#: Gemini on Vertex AI with Application Default Credentials (gcloud auth
#: application-default login); billed to this project.
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT")

pytestmark = pytest.mark.skipif(
    not (ANTHROPIC_KEY or GEMINI_KEY or VERTEX_PROJECT),
    reason="live model test: set ANTHROPIC_API_KEY, GEMINI_API_KEY or VERTEX_PROJECT",
)

PHONE_ID = "1098765432"

#: The catalogue, named the way a supplier's master lists them -- not the way
#: customers talk. (code, name, unit, MRP)
CATALOGUE = [
    ("OPC-53", "OPC Cement 53 Grade (50 kg bag)", "bags", "390.00"),
    ("PPC-50", "PPC Cement (50 kg bag)", "bags", "360.00"),
    ("WCEM-1", "White Cement 1 kg", "pcs", "45.00"),
    ("SAND-R", "River Sand (per ton)", "tons", "1800.00"),
    ("TMT-8", "TMT Steel Bar Fe500 8 mm (12 m)", "pcs", "310.00"),
    ("TMT-12", "TMT Steel Bar Fe500 12 mm (12 m)", "pcs", "690.00"),
    ("BRK-RED", "Red Clay Brick (standard)", "pcs", "9.00"),
    ("PNT-WE20", "Acrylic Emulsion Paint White 20 L", "buckets", "4200.00"),
    ("PVC-110", "PVC Pipe 110 mm (4 inch) 6 m length", "pcs", "980.00"),
    ("AGG-20", "Stone Aggregate 20 mm (per ton)", "tons", "1300.00"),
]

#: (id, sender name, message, expected status, expected {code: quantity} or None)
CASES: List[Tuple[str, str, str, str, Optional[Dict[str, int]]]] = [
    ("hinglish_cement_bori", "Ravi Builders",
     "Bhai 50 bori cement chahiye kal tak, 53 grade wala. Rate batao", "enquiry_created", {"OPC-53": 50}),
    ("hinglish_saria", "Mahesh Contractor",
     "12mm saria 100 nag bhej do site pe, kitna lagega?", "enquiry_created", {"TMT-12": 100}),
    ("hinglish_reti", "Sunil",
     "3 ton reti chahiye, nadi wali. price?", "enquiry_created", {"SAND-R": 3}),
    ("hinglish_eent", "Patel Construction",
     "Namaste, 5000 lal eent ka bhav kya hai?", "enquiry_created", {"BRK-RED": 5000}),
    ("gujarati_thela", "Jignesh Bhai",
     "cement na 10 thela joie che, PPC chalse. bhav moklo", "enquiry_created", {"PPC-50": 10}),
    ("english_paint", "Asha Interiors",
     "Hi, can you quote for 6 buckets of white emulsion, the 20 litre ones?", "enquiry_created", {"PNT-WE20": 6}),
    ("english_pipe_inches", "Kumar Plumbing",
     "Need 4 inch PVC pipes, 30 lengths. Please send rate.", "enquiry_created", {"PVC-110": 30}),
    ("multi_item_hinglish", "Shree Ganesh Developers",
     "Sir ji order ke liye rate chahiye: 25 bag cement 53 grade, 2 ton sand aur 8mm sariya 40 piece",
     "enquiry_created", {"OPC-53": 25, "SAND-R": 2, "TMT-8": 40}),
    ("gitti_slang", "Ramesh",
     "20mm gitti 5 tractor nahi, 5 ton chahiye. kab tak milegi aur rate?", "enquiry_created", {"AGG-20": 5}),
    ("no_quantity", "Neha",
     "white cement ka rate kya chal raha hai aajkal?", "enquiry_created", {"WCEM-1": 1}),
    ("not_enquiry_delivery", "Ravi Builders",
     "Kal ka truck abhi tak nahi aaya bhai, kab tak pahunchega?", "not_enquiry", None),
    ("not_enquiry_payment", "Mahesh Contractor",
     "Payment kar diya hai NEFT se, receipt bhej dena", "not_enquiry", None),
    ("not_enquiry_greeting", "Sunil",
     "Happy Diwali sir! 🪔", "not_enquiry", None),
    ("no_match_laptop", "Tech Solutions",
     "Do you have laptops? Need 5 for our office, quote please", "no_match", None),
]


def live_model():
    if ANTHROPIC_KEY:
        return ai_agent.chat_model(os.environ.get("LIVE_MODEL", "claude-opus-5-5"), ANTHROPIC_KEY)
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = os.environ.get("LIVE_MODEL", "gemini-3.1-flash-lite")
    if VERTEX_PROJECT:
        return ChatGoogleGenerativeAI(
            model=model, vertexai=True, project=VERTEX_PROJECT, location="global", max_retries=2
        )
    return ChatGoogleGenerativeAI(model=model, api_key=GEMINI_KEY, max_retries=2)


@pytest.fixture()
def live(client, session_factory, make_product, monkeypatch):
    monkeypatch.setattr(inbound, "session_factory", session_factory)
    model = live_model()
    monkeypatch.setattr(inbound, "model_factory", lambda name, key: model)
    for code, name, unit, mrp in CATALOGUE:
        make_product(name, sku=code, unit_of_measure=unit, mrp=mrp)
    # One customer already exists, as a phone number the agent must find.
    client.post("/api/customers", json={"name": "Ravi Builders", "phone": "+91 98765 43210"})
    assert client.put("/api/integrations/ai", json={
        "enabled": True, "credentials": {"api_key": "live-test"},
    }).status_code == 200
    assert client.put("/api/integrations/whatsapp", json={
        "enabled": True, "config": {"phone_number_id": PHONE_ID, "verify_token": "live"},
    }).status_code == 200
    return client


def webhook(case_id: str, name: str, text: str, sender: str) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{
        "field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550001111", "phone_number_id": PHONE_ID},
            "contacts": [{"profile": {"name": name}, "wa_id": sender}],
            "messages": [{"from": sender, "id": "wamid." + case_id, "timestamp": "1762500000",
                          "type": "text", "text": {"body": text}}],
        }}]}]}


@pytest.mark.parametrize("case_id,name,text,expected_status,expected_items", CASES, ids=[c[0] for c in CASES])
def test_agent_understands_the_message(live, case_id, name, text, expected_status, expected_items):
    sender = "919876543210" if name == "Ravi Builders" else "9198" + str(abs(hash(name)) % 10**8).zfill(8)
    response = live.post("/api/integrations/whatsapp/webhook", json=webhook(case_id, name, text, sender))
    assert response.status_code == 200 and response.json() == {"received": 1}

    message = live.get("/api/integrations/messages").json()["items"][0]
    got: Dict[str, D] = {}
    customer = None
    if message["enquiry_id"]:
        enquiry = live.get("/api/enquiries/{}".format(message["enquiry_id"])).json()
        got = {item["product"]["sku"]: D(item["quantity"]) for item in enquiry["items"]}
        customer = enquiry["customer"]["name"]
    print("\n[{}] {!r}\n  -> {} {} customer={} | {}{}".format(
        case_id, text, message["status"], {k: format(v.normalize(), "f") for k, v in got.items()}, customer,
        message["summary"] or "", (" ERROR " + message["error"]) if message["error"] else "",
    ))

    assert message["status"] == expected_status, message["error"] or message["summary"]
    if expected_items is not None:
        assert got == {code: D(qty) for code, qty in expected_items.items()}
    if name == "Ravi Builders" and expected_status == "enquiry_created":
        # The existing customer is found by phone, not created again.
        assert live.get("/api/customers", params={"search": "Ravi"}).json()["total"] == 1
