"""Twilio voice webhooks: the incoming-call instruction (TwiML) and the
media WebSocket. Mounted on the separate voice server (app.voice_main), so only
these endpoints are reachable from the internet."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Dict
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response

from .bridge import Call

router = APIRouter(prefix="/voice/twilio")


def _valid_signature(url: str, params: Dict[str, str], signature: str) -> bool:
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not token:
        return True
    payload = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature or "")


@router.post("/incoming")
async def incoming(request: Request):
    """Twilio calls this when the number rings: answer by streaming the call to us."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    public = os.environ.get("VOICE_PUBLIC_URL", "").rstrip("/")
    url = (public + request.url.path + ("?" + request.url.query if request.url.query else "")) if public else str(request.url)
    if not _valid_signature(url, form, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(status_code=403, detail="Bad signature")
    # For a call we placed ("call me"), the customer is the "To" number.
    caller = form.get("To") if form.get("Direction", "").startswith("outbound") else form.get("From", "")
    host = (public or str(request.base_url).rstrip("/")).replace("https://", "wss://").replace("http://", "ws://")
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
        f'<Stream url={quoteattr(host + "/voice/twilio/stream")}>'
        f'<Parameter name="from" value={quoteattr(caller or "")}/>'
        f'<Parameter name="to" value={quoteattr(form.get("To", ""))}/>'
        f'<Parameter name="mode" value={quoteattr(request.query_params.get("mode", "answer"))}/>'
        f'<Parameter name="booking" value={quoteattr(request.query_params.get("booking", ""))}/>'
        f'<Parameter name="task" value={quoteattr(request.query_params.get("task", ""))}/>'
        "</Stream></Connect></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@router.websocket("/stream")
async def stream(ws: WebSocket):
    await Call(ws).run()
