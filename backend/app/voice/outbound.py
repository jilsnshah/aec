"""Placing phone calls (Twilio): PAI calling a transporter to book a vehicle,
or a customer. The call is answered by the voice server, which streams it to
the voice model with the right instructions for the purpose."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlencode

import httpx

#: Tests replace this with a client on a mock transport.
http_factory = lambda: httpx.Client(timeout=20)  # noqa: E731


def _env() -> Dict[str, str]:
    """Twilio settings from the environment, or from backend/.env.voice."""
    keys = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_NUMBER", "VOICE_PUBLIC_URL")
    values = {k: os.environ.get(k, "") for k in keys}
    if not all(values.values()):
        env = Path(__file__).resolve().parent.parent.parent / ".env.voice"
        if env.exists():
            for line in env.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    if key.strip() in values and not values[key.strip()]:
                        values[key.strip()] = value.strip()
    return values


def configured() -> bool:
    return all(_env().values())


def place_call(to: str, mode: str, params: Optional[Dict[str, str]] = None) -> str:
    """Ring ``to``; returns Twilio's call id. Raises RuntimeError when calling is not set up."""
    env = _env()
    if not all(env.values()):
        raise RuntimeError("Phone calls are not set up (Twilio number and voice server).")
    number = "".join(ch for ch in to if ch.isdigit() or ch == "+")
    if not number.startswith("+"):
        number = "+91" + number[-10:]
    query = urlencode({"mode": mode, **(params or {})})
    with http_factory() as client:
        response = client.post(
            "https://api.twilio.com/2010-04-01/Accounts/{}/Calls.json".format(env["TWILIO_ACCOUNT_SID"]),
            auth=(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"]),
            data={"To": number, "From": env["TWILIO_NUMBER"], "Url": "{}/voice/twilio/incoming?{}".format(env["VOICE_PUBLIC_URL"].rstrip("/"), query)},
        )
    if response.status_code >= 300:
        raise RuntimeError("Twilio refused the call: {}".format(response.json().get("message", response.status_code)))
    return response.json().get("sid", "")
