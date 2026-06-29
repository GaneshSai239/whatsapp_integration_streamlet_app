"""Demo app hosting the two things you need:

    1. WebSocket updates   ->  ws://localhost:8080/ws        (websocket.py)
    2. Send API            ->  POST /api/send/*              (send_message.py)

Plus the Meta webhook (websocket.py) that feeds updates into the stream.

Run:
    uvicorn app:app --host 0.0.0.0 --port 8080
    # or: python app.py
Docs: http://localhost:8080/docs
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parent / ".env")

import send_message
import tracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="WhatsApp Demo App", version="1.0.0")

app.include_router(tracker.router)      # /webhook + /ws
app.include_router(send_message.router)   # /api/send/*


@app.get("/", tags=["health"], summary="Health check")
def health():
    return {
        "service": "WhatsApp Demo App",
        "websocket": "/ws",
        "send": ["/api/send/text", "/api/send/template", "/api/send/interactive"],
        "webhook": "/webhook",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=False)
