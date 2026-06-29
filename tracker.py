"""Incoming updates: Meta webhook ingestion + WebSocket live stream.

- GET  /webhook : Meta verification handshake
- POST /webhook : receives messages/statuses, stores them, and fans them out
- WS   /ws      : streams every stored event to connected clients in real time

Events are shared via Redis pub/sub so the webhook (which writes) and the
WebSocket (which reads) stay decoupled.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

import redis
import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

load_dotenv(Path(__file__).resolve().parent / ".env")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
APP_SECRET = os.getenv("APP_SECRET", "")
STRICT_SIGNATURE = os.getenv("STRICT_SIGNATURE", "0") == "1"
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

EVENTS_CHANNEL = "wa:events"
MESSAGES_KEY = "wa:messages"
MAX_MESSAGES = 500

log = logging.getLogger("websocket")
router = APIRouter()

_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def add_message(record: dict) -> dict:
    """Store an event (capped history) and publish it to WebSocket listeners."""
    record.setdefault("ts", time.time())
    payload = json.dumps(record)
    try:
        _redis.rpush(MESSAGES_KEY, payload)
        _redis.ltrim(MESSAGES_KEY, -MAX_MESSAGES, -1)
        _redis.publish(EVENTS_CHANNEL, payload)
    except redis.RedisError as exc:
        log.warning("Redis error while storing message: %s", exc)
    return record


def get_messages(limit: int = 50) -> list[dict]:
    try:
        return [json.loads(x) for x in _redis.lrange(MESSAGES_KEY, -limit, -1)]
    except redis.RedisError:
        return []


def _signature_ok(raw_body: bytes, header: str | None) -> bool:
    if not APP_SECRET:
        return False
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def _parse(message: dict) -> dict:
    msg_type = message.get("type")
    if msg_type == "text":
        text = message.get("text", {}).get("body", "")
    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        text = reply.get("title", "")
    else:
        text = ""
    return {"type": msg_type or "unknown", "text": text}


@router.get("/webhook", summary="Webhook verification handshake")
def verify(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)


@router.post("/webhook", summary="Receive WhatsApp events")
async def receive(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not _signature_ok(raw_body, signature) and STRICT_SIGNATURE:
        return PlainTextResponse("Invalid signature", status_code=403)

    try:
        body = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        return PlainTextResponse("Bad request", status_code=400)

    if body.get("object") == "whatsapp_business_account":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                for status in value.get("statuses", []) or []:
                    add_message(
                        {
                            "direction": "status",
                            "to": status.get("recipient_id"),
                            "type": "status:" + str(status.get("status")),
                            "text": f"{status.get('id')} -> {status.get('status')}",
                            "id": status.get("id"),
                        }
                    )
                for message in value.get("messages", []) or []:
                    parsed = _parse(message)
                    add_message(
                        {
                            "direction": "inbound",
                            "from": message.get("from"),
                            "type": parsed["type"],
                            "text": parsed["text"],
                            "id": message.get("id"),
                        }
                    )

    return PlainTextResponse("EVENT_RECEIVED", status_code=200)


@router.websocket("/ws")
async def stream(websocket: WebSocket):
    await websocket.accept()

    for message in get_messages(50):
        await websocket.send_json(message)

    client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                await websocket.send_text(message["data"])
            else:
                await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        log.info("WebSocket client disconnected.")
    except Exception as exc:  # noqa: BLE001
        log.warning("WebSocket error: %s", exc)
    finally:
        try:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.aclose()
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
