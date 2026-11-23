"""Phone calls on Sarvam instead of Gemini Live.

The call's audio (8 kHz mu-law from Twilio) streams to Sarvam's real-time
speech-to-text; each finished sentence from the caller goes to Sarvam's chat
model with the same instructions and tools the Gemini agent gets; the reply is
spoken with Sarvam's Bulbul voice, returned as 8 kHz mu-law and played straight
into the call. When the caller starts talking over the agent, the agent stops.

Chosen in Settings -> AI (voice_provider = "sarvam"); the key is the Sarvam API
key saved there or SARVAM_API_KEY in the voice server's environment.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
import websockets
from fastapi import WebSocketDisconnect

from ..database import SessionLocal
from ..services import integration_settings as settings_service

logger = logging.getLogger(__name__)

API = "https://api.sarvam.ai"
STT_URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws"
#: Gemini voices the agents' profiles use, by whether they sound male.
MALE_VOICES = {"Puck", "Charon", "Fenrir", "Orus"}
#: A Bulbul voice per language for a male- or female-sounding agent.
SPEAKERS = {
    ("hi-IN", "male"): "rahul_hi_conversational", ("hi-IN", "female"): "kavya_hi_conversational",
    ("gu-IN", "male"): "bhavik_gu_conversation", ("gu-IN", "female"): "pooja_gu_conversational",
    ("en-IN", "male"): "dev_en_conversational", ("en-IN", "female"): "simran_en_conversation",
}
SPEAK_RULES = """

You are speaking on a phone call: your reply is turned into speech.
- Start in {language}. Switch only when they speak a full sentence in another language (Hindi, Gujarati, English or a mix);
  "hello", "haan", "ok" and other one-word replies do not change the language.
- One short sentence or two, and ONE question at a time. Do not repeat a question they have already answered.
- Short replies like "haan", "hmm", "bolo", "ok" mean they are listening or saying go on: continue, do not ask again.
- Never add up or multiply prices; repeat only the per-unit price they said. Write numbers as a person would say them.
- No lists, markdown, emojis, brackets or asterisks, and never a tool name.
- Write Hindi in Devanagari and Gujarati in Gujarati script; English words in English."""
LANGUAGE_NAMES = {"hi-IN": "Hindi", "gu-IN": "Gujarati", "en-IN": "English", "mr-IN": "Marathi", "bn-IN": "Bengali", "ta-IN": "Tamil",
                  "te-IN": "Telugu", "kn-IN": "Kannada", "ml-IN": "Malayalam", "pa-IN": "Punjabi", "od-IN": "Odia"}
#: What a listener says to keep the speaker going; never an interruption.
BACKCHANNEL = {"haan", "han", "ha", "hmm", "hm", "hmmm", "ok", "okay", "ji", "haanji", "bolo", "achha", "accha", "theek", "yes", "oh", "ho",
               "हाँ", "हां", "हम्म", "जी", "बोलो", "अच्छा", "ठीक", "હા", "હમ", "હમ્મ", "બોલો", "જી", "સારું", "ઓકે"}
FRAME = 800  # 100 ms of 8 kHz mu-law per message to Sarvam


def _schema(schema: Any) -> Dict[str, Any]:
    """A Gemini function schema as JSON Schema for an OpenAI-style tool."""
    if schema is None:
        return {"type": "object", "properties": {}}
    kind = getattr(schema.type, "value", schema.type)
    out: Dict[str, Any] = {"type": str(kind or "object").lower()}
    if schema.description:
        out["description"] = schema.description
    if schema.properties:
        out["properties"] = {name: _schema(value) for name, value in schema.properties.items()}
    if schema.items is not None:
        out["items"] = _schema(schema.items)
    if schema.required:
        out["required"] = list(schema.required)
    if schema.enum:
        out["enum"] = list(schema.enum)
    if out["type"] == "object":
        out.setdefault("properties", {})
    return out


def tool_specs(declarations: List[Any]) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": {"name": d.name, "description": d.description or "", "parameters": _schema(d.parameters)}}
            for d in declarations]


def _backchannel(text: str) -> bool:
    words = [w.strip(".,!?।").lower() for w in text.split()]
    return 0 < len(words) <= 2 and all(w in BACKCHANNEL for w in words)


def _script_language(text: str, fallback: str) -> str:
    """The language to speak a sentence in, from the script it is written in."""
    gujarati = sum(1 for ch in text if "\u0a80" <= ch <= "\u0aff")
    devanagari = sum(1 for ch in text if "\u0900" <= ch <= "\u097f")
    if gujarati > devanagari and gujarati:
        return "gu-IN"
    if devanagari:
        return "hi-IN"
    return fallback


def _sentences(text: str) -> List[str]:
    """Split a reply so the first sentence can be spoken while the next is made."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?।])\s+", text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


class SarvamEngine:
    def __init__(self, call: Any, system: str, declarations: List[Any], greeting: str, voice: Dict[str, Any], profile: Dict[str, Any]):
        session = SessionLocal()
        try:
            key = settings_service.sarvam_key(session)
            llm_key = settings_service.voice_llm_key(session) if voice.get("llm_base_url") else None
        finally:
            session.close()
        if not key:
            raise RuntimeError("Voice calls are set to Sarvam but no Sarvam API key is saved.")
        self.call = call
        self.key = key
        language = voice.get("language") or "hi-IN"
        rules = SPEAK_RULES.replace("{language}", LANGUAGE_NAMES.get(language, "Hindi"))
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": system + rules}, {"role": "user", "content": greeting}]
        self.tools = tool_specs(declarations)
        self.voice = voice
        self.gender = "male" if (profile.get("voice") or "") in MALE_VOICES else "female"
        self.language = voice.get("language") or "hi-IN"
        self.http = httpx.AsyncClient(base_url=API, timeout=30, headers={"api-subscription-key": key})
        # The chat model: Sarvam's API, or any OpenAI-compatible one set in Settings.
        self.llm_url = (voice.get("llm_base_url") + "/chat/completions") if voice.get("llm_base_url") else API + "/v2/chat/completions"
        self.llm_headers = {"Authorization": "Bearer " + llm_key} if voice.get("llm_base_url") else {"api-subscription-key": key}
        self.on_sarvam = not voice.get("llm_base_url")
        self.use_gemini = voice.get("chat") == "gemini"
        if self.use_gemini:
            from google.genai import types

            from .bridge import _text_client

            self.gemini = _text_client()
            self.gemini_config = types.GenerateContentConfig(
                system_instruction=self.messages[0]["content"], temperature=0.3, max_output_tokens=300,
                tools=[types.Tool(function_declarations=declarations)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
            self.contents = [types.Content(role="user", parts=[types.Part(text=greeting)])]
        self.reply_task: Optional[asyncio.Task] = None
        self.audio_until = 0.0  # when the audio already sent to the call finishes playing
        self.ended = asyncio.Event()

    # --- the call -----------------------------------------------------------------

    async def run(self) -> None:
        query = urlencode({"model": "saaras:v4", "language_code": "auto", "encoding": "mulaw", "sample_rate": 8000,
                           "mode": "codemix", "stream_type": "fast", "silence_duration_ms": 700})
        try:
            async with websockets.connect("{}?{}".format(STT_URL, query), additional_headers={"api-subscription-key": self.key},
                                          max_size=None, ping_interval=20) as stt:
                self.stt = stt
                self.reply_task = asyncio.create_task(self._reply())
                await asyncio.gather(self._from_twilio(), self._from_stt())
        finally:
            if self.reply_task:
                self.reply_task.cancel()
            await self.http.aclose()

    async def _from_twilio(self) -> None:
        buffer = b""
        try:
            while not self.ended.is_set():
                frame = json.loads(await self.call.ws.receive_text())
                event = frame.get("event")
                if event == "media":
                    buffer += base64.b64decode(frame["media"]["payload"])
                    if len(buffer) >= FRAME:
                        await self.stt.send(json.dumps({"event": "audio_input", "audio": base64.b64encode(buffer).decode()}))
                        buffer = b""
                elif event == "stop":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self.ended.set()
            try:
                await self.stt.send(json.dumps({"event": "end"}))
                await self.stt.close()
            except Exception:
                pass

    async def _from_stt(self) -> None:
        try:
            async for raw in self.stt:
                message = json.loads(raw)
                event = message.get("event")
                if event == "transcript.partial" and self._speaking() and len((message.get("text") or "").split()) >= 3:
                    await self._interrupt()  # they are really talking over the agent, not just saying "haan"
                elif event == "transcript.final":
                    text = (message.get("text") or "").strip()
                    if not text:
                        continue
                    if self._speaking() and _backchannel(text):
                        self.call._say("caller", text)
                        self.call._flush("caller")
                        continue  # "haan" while the agent talks: keep talking
                    language = message.get("language")
                    if language and (language, self.gender) in SPEAKERS:
                        self.language = language  # answer in the language they speak
                    self.call._flush("ai")
                    self.call._say("caller", text)
                    self.call._flush("caller")
                    self.messages.append({"role": "user", "content": text})
                    if self.use_gemini:
                        from google.genai import types

                        self.contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
                    await self._interrupt()
                    self.reply_task = asyncio.create_task(self._reply())
                elif event == "error":
                    logger.warning("Sarvam speech-to-text: %s", message.get("message"))
                    if message.get("is_fatal"):
                        break
        except websockets.ConnectionClosed:
            pass
        finally:
            self.ended.set()

    def _speaking(self) -> bool:
        return (self.reply_task is not None and not self.reply_task.done()) or time.monotonic() < self.audio_until

    async def _interrupt(self) -> None:
        """The caller spoke: stop talking and drop what is queued on the line."""
        if self.reply_task is not None and not self.reply_task.done():
            self.reply_task.cancel()
        if time.monotonic() < self.audio_until:
            await self.call._send({"event": "clear", "streamSid": self.call.stream_sid})
            self.audio_until = 0.0

    # --- thinking and speaking ------------------------------------------------------

    async def _reply_gemini(self) -> None:
        """Gemini decides: tool calls run here, its text is spoken by Sarvam."""
        from google.genai import types

        for _ in range(5):
            response = await self.gemini.aio.models.generate_content(model=self.voice.get("gemini_model") or "gemini-3.5-flash-lite",
                                                                     contents=self.contents, config=self.gemini_config)
            content = response.candidates[0].content if response.candidates else None
            if content is None or not content.parts:
                return
            self.contents.append(content)
            calls = [p.function_call for p in content.parts if p.function_call]
            text = " ".join(p.text for p in content.parts if p.text and not getattr(p, "thought", False)).strip()
            if text:
                await self._speak(text)
            if not calls:
                return
            results = []
            for call in calls:
                result = await asyncio.to_thread(self.call.tools.run, call.name, dict(call.args or {}))
                results.append(types.Part(function_response=types.FunctionResponse(id=call.id, name=call.name, response=result)))
            self.contents.append(types.Content(role="user", parts=results))

    async def _reply(self) -> None:
        try:
            if self.use_gemini:
                await self._reply_gemini()
                if self.call.tools and self.call.tools.hangup:
                    await asyncio.sleep(max(0.0, self.audio_until - time.monotonic()) + 0.8)
                    self.ended.set()
                    await self.call.ws.close()
                return
            for _ in range(5):  # tool calls, then the spoken answer
                body = {"model": self.voice.get("chat_model") or "deepseekv4.1-flash-1017-interactive", "messages": self.messages, "tools": self.tools,
                        "tool_choice": "auto", "temperature": 0.3, "max_tokens": 300}
                headers = dict(self.llm_headers)
                if self.on_sarvam:
                    body["reasoning_effort"] = "low" if body["model"].startswith("glm") else "none"
                    headers["x-session-affinity"] = str(self.call.call_sid or "")
                response = await self.http.post(self.llm_url, json=body, headers=headers)
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                calls = message.get("tool_calls") or []
                if calls:
                    self.messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
                    for item in calls:
                        try:
                            args = json.loads(item["function"].get("arguments") or "{}")
                        except ValueError:
                            args = {}
                        result = await asyncio.to_thread(self.call.tools.run, item["function"]["name"], args)
                        self.messages.append({"role": "tool", "tool_call_id": item["id"], "content": json.dumps(result, default=str)})
                    if message.get("content"):
                        await self._speak(message["content"])
                    continue
                text = (message.get("content") or "").strip()
                self.messages.append({"role": "assistant", "content": text})
                await self._speak(text)
                break
            if self.call.tools and self.call.tools.hangup:
                await asyncio.sleep(max(0.0, self.audio_until - time.monotonic()) + 0.8)
                self.ended.set()
                await self.call.ws.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Sarvam reply failed on call %s", self.call.call_sid)

    async def _speak(self, text: str) -> None:
        text = re.sub(r"\*[^*]{0,80}\*", "", text).strip()
        if not text:
            return
        self.call._flush("caller")
        self.call._say("ai", text + " ")
        self.call._flush("ai")
        for sentence in _sentences(text):
            language = _script_language(sentence, self.language if (self.language, self.gender) in SPEAKERS else "hi-IN")
            speaker = self.voice.get("voice") or SPEAKERS.get((language, self.gender)) or SPEAKERS[("hi-IN", self.gender)]
            response = await self.http.post("/text-to-speech", json={
                "text": sentence[:2400], "language_code": language,
                "speaker": speaker, "model": self.voice.get("tts_model") or "bulbul:v4-flash",
                "speech_sample_rate": 8000, "output_audio_codec": "mulaw"})
            if response.status_code >= 300:
                logger.warning("Sarvam voice failed: %s", response.text[:300])
                return
            audio = b"".join(base64.b64decode(a) for a in response.json().get("audios") or [])
            for i in range(0, len(audio), 1600):  # 200 ms frames
                await self.call._send({"event": "media", "streamSid": self.call.stream_sid,
                                       "media": {"payload": base64.b64encode(audio[i:i + 1600]).decode()}})
            self.audio_until = max(self.audio_until, time.monotonic()) + len(audio) / 8000
