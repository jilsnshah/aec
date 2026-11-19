"""Bridge a Twilio Media Stream to Gemini Live.

Twilio sends the caller's audio as 8 kHz mu-law in base64 JSON frames over a
WebSocket and plays back what we send the same way. Gemini Live takes 16 kHz
16-bit PCM and speaks 24 kHz 16-bit PCM. This module converts between them,
runs the receptionist's tools, handles barge-in (the caller talking over the
AI clears queued audio), and saves the call with its transcript.
"""
from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from ..config import get_settings
from ..database import SessionLocal
from ..models import PhoneCall
from ..services import integration_settings as settings_service
from .tools import DECLARATIONS, CallTools

logger = logging.getLogger(__name__)

#: Cheapest live voice model first; the next is used if it is unavailable.
VOICE_MODELS = [m for m in os.environ.get("VOICE_MODEL", "gemini-live-2.5-flash-native-audio,gemini-3.8-live").split(",") if m]
VOICE_LOCATION = os.environ.get("VOICE_LOCATION", "us-central1")
VOICE_NAME = os.environ.get("VOICE_NAME", "Aoede")
AGENT_NAME = os.environ.get("VOICE_AGENT_NAME", "Asha")


def _seller() -> str:
    session = SessionLocal()
    try:
        return settings_service.get(session, settings_service.TALLY).config.get("seller_name") or "our shop"
    finally:
        session.close()


def instructions(seller: str, brief: str) -> str:
    from ..services import integration_settings as settings_service

    session = SessionLocal()
    try:
        knowledge = settings_service.company_knowledge(session)
        agent_name = settings_service.get(session, settings_service.AI).config.get("agent_name") or AGENT_NAME
    finally:
        session.close()
    return _instructions(seller, brief, agent_name, knowledge)


def _instructions(seller: str, brief: str, AGENT_NAME: str, knowledge: str) -> str:
    return f"""What you know about the business (answer from this and the tools only):
{knowledge or '(nothing written yet)'}

You are {AGENT_NAME}, the virtual assistant of {seller}, a building materials and hardware trader in India \
(cement, steel, sand, packaging and more). If asked your name, say "{AGENT_NAME}, {seller}'s virtual assistant"; never say \
Gemini or Google. If asked whether you are a person, say honestly that you are an AI assistant. You are on a phone call, so:
- Keep every reply short: one or two sentences, natural spoken language, no lists, no markdown.
- Speak the caller's language: Gujarati, Hindi, English or a mix, exactly as they do; switch if they switch. Numbers in words a person says aloud ("three hundred and forty rupees a bag").
- Prices are before GST. Quote only prices that find_products returns; never invent prices, stock or dates.
- When asked how much stock, price or what is available, ANSWER WITH THE NUMBERS from find_products (e.g. "we have \
eleven boxes of large cartons at eighty rupees each"). Never dodge with "various quantities".
- You can: check products, stock and the caller's price; tell a recognised caller about their open orders and what they owe; \
take an enquiry (a quote request) for the sales team.
- To take an enquiry: find each product, confirm quantities, read the whole list back, and only after the caller agrees call take_enquiry. \
Then say the enquiry number and that the team will confirm price and delivery shortly.
- If the caller is recognised and wants to order, prepare_order, read the summary back with the total and ask \
for a clear yes; only then place_order and say exactly what it returned. If ordering is not allowed, take an enquiry.
- Never give extra discounts or promise delivery dates: say the team will confirm.
- Never share one customer's information with anyone else. If the caller is not recognised, do not discuss orders or balances.
- If they want a person, say someone will call them back soon (note it in the enquiry notes if there is one).
- When they are done, say a short goodbye and call end_call.
{brief}"""


PITCH = """

THIS IS AN OUTBOUND SALES CALL that you placed. Introduce yourself as calling from the business. First call find_products \
with a broad query such as "cement", "steel", "sand" or "carton" to learn what is in stock and the prices. Then give a short, \
warm pitch: two or three products that are in stock, ALWAYS saying the quantity available and the price per unit, and why they are a good buy (in stock now, \
quick delivery from our yard, bulk prices on request). Ask about their current project and what they need. Do not read long \
lists. If they are interested, offer to take an enquiry so the team sends a quote. If they are busy, thank them and end politely."""


def _client() -> genai.Client:
    settings = get_settings()
    creds = settings_service.ai_credentials(None)
    if settings.vertex_project:
        return genai.Client(vertexai=True, project=settings.vertex_project, location=VOICE_LOCATION)
    if creds and creds.get("api_key"):
        return genai.Client(api_key=creds["api_key"])
    raise RuntimeError("No Gemini credentials for voice.")


class Call:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.caller: Optional[str] = None
        self.to: Optional[str] = None
        self.tools: Optional[CallTools] = None
        self.transcript: List[Dict[str, str]] = []
        self.started = datetime.now(timezone.utc)
        self.in_state = None   # audioop.ratecv state, caller -> model
        self.out_state = None  # model -> caller
        self.record_id = None
        self.mode = "answer"
        self._partial = {"caller": "", "ai": ""}

    def _say(self, who: str, text: str) -> None:
        self._partial[who] += text

    def _flush(self, who: str) -> None:
        text = self._partial[who].strip()
        if text:
            self.transcript.append({"who": who, "text": text, "at": datetime.now(timezone.utc).isoformat()})
        self._partial[who] = ""

    async def run(self) -> None:
        await self.ws.accept()
        # Wait for Twilio's "start" frame: it carries the call and caller.
        while self.stream_sid is None:
            frame = json.loads(await self.ws.receive_text())
            if frame.get("event") == "start":
                start = frame["start"]
                self.stream_sid, self.call_sid = start["streamSid"], start.get("callSid")
                params = start.get("customParameters") or {}
                self.caller, self.to = params.get("from"), params.get("to")
                self.mode = params.get("mode", "answer")
        self.tools = CallTools(SessionLocal, self.caller)
        brief = await asyncio.to_thread(self.tools.identify)
        self._open_record()
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=instructions(await asyncio.to_thread(_seller), brief) + (PITCH if self.mode == "pitch" else ""),
            tools=[types.Tool(function_declarations=DECLARATIONS)],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME))),
        )
        try:
            client = _client()
            connection = None
            for model in VOICE_MODELS:
                try:
                    connection = client.aio.live.connect(model=model, config=config)
                    session_ctx = await connection.__aenter__()
                    self.model = model
                    break
                except Exception:
                    logger.warning("Voice model %s unavailable, trying the next", model)
                    connection = None
            if connection is None:
                raise RuntimeError("No live voice model available.")
            session = session_ctx
            try:
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=(
                        "(You placed this call and the person just picked up. Introduce yourself and the business, then start the pitch.)"
                        if self.mode == "pitch" else "(The phone call has just connected. Greet the caller and ask how you can help.)"))]),
                    turn_complete=True,
                )
                await asyncio.gather(self._from_twilio(session), self._from_gemini(session))
            finally:
                await connection.__aexit__(None, None, None)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            if "1000" in str(exc) or "ConnectionClosed" in type(exc).__name__:
                logger.info("Voice call %s ended", self.call_sid)  # normal hang-up
            else:
                logger.exception("Voice call %s failed", self.call_sid)
        finally:
            await asyncio.to_thread(self._close_record)

    async def _from_twilio(self, session) -> None:
        try:
            while True:
                frame = json.loads(await self.ws.receive_text())
                event = frame.get("event")
                if event == "media":
                    mulaw = base64.b64decode(frame["media"]["payload"])
                    pcm8 = audioop.ulaw2lin(mulaw, 2)
                    pcm16, self.in_state = audioop.ratecv(pcm8, 2, 1, 8000, 16000, self.in_state)
                    await session.send_realtime_input(audio=types.Blob(data=pcm16, mime_type="audio/pcm;rate=16000"))
                elif event == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await session.close()

    async def _from_gemini(self, session) -> None:
        while True:
            async for message in session.receive():
                content = message.server_content
                if content:
                    if content.interrupted:
                        # The caller spoke over the AI: drop what is queued.
                        await self._send({"event": "clear", "streamSid": self.stream_sid})
                        self.out_state = None
                    if content.input_transcription and content.input_transcription.text:
                        self._flush("ai")
                        self._say("caller", content.input_transcription.text)
                    if content.output_transcription and content.output_transcription.text:
                        self._flush("caller")
                        self._say("ai", content.output_transcription.text)
                    if content.model_turn:
                        for part in content.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                await self._play(part.inline_data.data)
                    if content.turn_complete:
                        self._flush("caller")
                        self._flush("ai")
                        if self.tools and self.tools.hangup:
                            await asyncio.sleep(2.5)  # let the goodbye finish playing
                            await self.ws.close()
                            return
                if message.tool_call:
                    responses = []
                    for call in message.tool_call.function_calls or []:
                        result = await asyncio.to_thread(self.tools.run, call.name, dict(call.args or {}))
                        responses.append(types.FunctionResponse(id=call.id, name=call.name, response=result))
                    await session.send_tool_response(function_responses=responses)

    async def _play(self, pcm24: bytes) -> None:
        pcm8, self.out_state = audioop.ratecv(pcm24, 2, 1, 24000, 8000, self.out_state)
        mulaw = audioop.lin2ulaw(pcm8, 2)
        for i in range(0, len(mulaw), 1600):  # 200 ms frames
            await self._send({"event": "media", "streamSid": self.stream_sid, "media": {"payload": base64.b64encode(mulaw[i:i + 1600]).decode()}})

    async def _send(self, frame: Dict[str, Any]) -> None:
        try:
            await self.ws.send_text(json.dumps(frame))
        except Exception:
            pass

    def _open_record(self) -> None:
        session = SessionLocal()
        try:
            call = PhoneCall(provider="twilio", provider_call_id=self.call_sid, direction="in", from_number=self.caller,
                             to_number=self.to, customer_id=self.tools.customer_id if self.tools else None)
            session.add(call)
            session.commit()
            self.record_id = call.id
        finally:
            session.close()

    def _close_record(self) -> None:
        self._flush("caller")
        self._flush("ai")
        session = SessionLocal()
        try:
            call = session.get(PhoneCall, self.record_id) if self.record_id else None
            if call is None:
                return
            ended = datetime.now(timezone.utc)
            call.ended_at = ended
            call.duration_seconds = int((ended - self.started).total_seconds())
            call.status = "completed"
            call.transcript = self.transcript
            call.actions = self.tools.actions if self.tools else []
            call.customer_id = self.tools.customer_id if self.tools else call.customer_id
            call.enquiry_id = self.tools.enquiry_id if self.tools else None
            call.summary = _summary(self.transcript, self.tools)
            session.commit()
        finally:
            session.close()


def _summary(transcript: List[Dict[str, str]], tools: Optional[CallTools]) -> str:
    who = tools.customer_name if tools and tools.customer_name else "Unknown caller"
    did = ", ".join(sorted({a["tool"].replace("_", " ") for a in (tools.actions if tools else [])})) or "conversation only"
    first = next((t["text"] for t in transcript if t["who"] == "caller"), "")
    return "{}: {}. Asked: {}".format(who, did, first[:200])
