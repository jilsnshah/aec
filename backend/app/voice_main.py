"""The voice server: only the phone endpoints, run separately from the main app
so that exposing it to Twilio (through a tunnel or a public host) exposes
nothing else.

    uvicorn app.voice_main:app --port 8107
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

env = Path(__file__).resolve().parent.parent / ".env.voice"
if env.exists():
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from .logging_config import configure_logging  # noqa: E402
from .voice.routes import router  # noqa: E402

configure_logging()
app = FastAPI(title="AEC voice", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)


@app.get("/voice/health")
def health():
    return {"status": "ok"}
