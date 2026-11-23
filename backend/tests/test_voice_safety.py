"""Phone safety and the Sarvam call engine's helpers."""
from __future__ import annotations

import pytest

from app.voice import outbound
from app.voice.sarvam import _backchannel, _script_language, tool_specs
from app.voice.tools import SUPPLIER_QUOTE_DECLARATIONS


def test_only_allowed_numbers_are_called(monkeypatch):
    monkeypatch.setenv("VOICE_ALLOWED_NUMBERS", "+917000000001")
    monkeypatch.setattr(outbound, "_env", lambda: {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_NUMBER": "+1", "VOICE_PUBLIC_URL": "https://x"})
    dialled = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, auth, data):
            dialled.append(data["To"])
            return type("R", (), {"status_code": 201, "json": lambda self: {"sid": "CA1"}})()

    monkeypatch.setattr(outbound, "http_factory", Client)
    with pytest.raises(RuntimeError, match="blocked"):
        outbound.place_call("9000012345", "supplier_quote")
    assert outbound.place_call("7000000001", "supplier_quote") == "CA1" and dialled == ["+917000000001"]


def test_purchasing_tools_cannot_order_and_convert_for_sarvam():
    specs = tool_specs(SUPPLIER_QUOTE_DECLARATIONS)
    names = {s["function"]["name"] for s in specs}
    assert "record_quote" in names and not names & {"order_now", "confirm_order"}
    lines = next(s for s in specs if s["function"]["name"] == "record_quote")["function"]["parameters"]["properties"]["lines"]
    assert lines["type"] == "array" and lines["items"]["required"] == ["item", "price"]


def test_listening_words_and_script_language():
    assert _backchannel("Han han.") and _backchannel("હમ્મ") and not _backchannel("3,000 અને GST extra")
    assert _script_language("નમસ્તે Ravi", "hi-IN") == "gu-IN" and _script_language("नमस्ते", "gu-IN") == "hi-IN"
    assert _script_language("Hello", "en-IN") == "en-IN"
