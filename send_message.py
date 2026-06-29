"""Outbound messaging via the WhatsApp Cloud API.

Endpoints:
- POST /api/send/text         { to, body }
- POST /api/send/template     { to, name, language, body_params[] }
- POST /api/send/interactive  { to, text, buttons[] }

Every successful send is also recorded to the live feed (so it shows up on /ws).
"""

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tracker import add_message

load_dotenv(Path(__file__).resolve().parent / ".env")

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v25.0")
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

router = APIRouter(prefix="/api/send", tags=["send"])


def _post(body: dict[str, Any]) -> dict[str, Any]:
    resp = requests.post(
        f"{BASE_URL}/{PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}
    if not resp.ok:
        raise HTTPException(status_code=resp.status_code, detail=data)
    return data


def _message_id(resp: dict[str, Any]) -> str:
    try:
        return resp.get("messages", [{}])[0].get("id", "")
    except (AttributeError, IndexError):
        return ""


class TextMessage(BaseModel):
    to: str = Field(..., description="Recipient phone number with country code, e.g. 15551234567")
    body: str


class TemplateMessage(BaseModel):
    to: str
    name: str
    language: str = "en_US"
    body_params: list[str] = Field(default_factory=list)


class ReplyButton(BaseModel):
    id: str
    title: str


class InteractiveMessage(BaseModel):
    to: str
    text: str
    buttons: list[ReplyButton]


@router.post("/text", summary="Send a text message")
def send_text(payload: TextMessage):
    resp = _post(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": payload.to,
            "type": "text",
            "text": {"preview_url": False, "body": payload.body},
        }
    )
    mid = _message_id(resp)
    add_message({"direction": "outbound", "to": payload.to, "type": "text", "text": payload.body, "id": mid, "source": "api"})
    return {"message_id": mid, "raw": resp}


@router.post("/template", summary="Send a template message")
def send_template(payload: TemplateMessage):
    template: dict[str, Any] = {"name": payload.name, "language": {"code": payload.language}}
    if payload.body_params:
        template["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in payload.body_params]}
        ]
    resp = _post(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": payload.to,
            "type": "template",
            "template": template,
        }
    )
    mid = _message_id(resp)
    text = f"[template] {payload.name} ({', '.join(payload.body_params)})"
    add_message({"direction": "outbound", "to": payload.to, "type": "template", "text": text, "id": mid, "source": "api"})
    return {"message_id": mid, "raw": resp}


@router.post("/interactive", summary="Send interactive reply buttons")
def send_interactive(payload: InteractiveMessage):
    resp = _post(
        {
            "messaging_product": "whatsapp",
            "to": payload.to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": payload.text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in payload.buttons
                    ]
                },
            },
        }
    )
    mid = _message_id(resp)
    add_message({"direction": "outbound", "to": payload.to, "type": "interactive", "text": payload.text, "id": mid, "source": "api"})
    return {"message_id": mid, "raw": resp}
