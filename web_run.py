"""Tiny WebSocket client to watch the live message stream.

The app (app.py) must already be running on :8080. Then:

    ./venv/bin/python web_run.py

It connects to ws://localhost:8080/ws and prints every event the server
pushes (inbound messages, outbound echoes, and delivery/read statuses).
Press Ctrl+C to quit.

Optional: send a fake inbound event (handy for testing without a real phone):

    ./venv/bin/python web_run.py --simulate
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import websockets
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

WS_URL = os.getenv("WS_URL", "ws://localhost:8080/ws")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://localhost:8080/webhook")


def _format(event: dict) -> str:
    direction = event.get("direction", "?")
    msg_type = event.get("type", "")
    who = event.get("from") or event.get("to") or ""
    text = event.get("text", "")
    return f"[{direction:<8}] {who:<15} {msg_type:<14} {text}"


async def _simulate():
    """POST a fake inbound text message to the webhook (for local testing)."""
    import urllib.request

    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "15551234567",
                                        "type": "text",
                                        "text": {"body": "hello from web_run --simulate"},
                                        "id": "wamid.SIMULATED",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
    ).encode()
    req = urllib.request.Request(WEBHOOK_URL, data=body, headers={"Content-Type": "application/json"})
    print("simulate -> webhook responded:", urllib.request.urlopen(req).read().decode())


async def main(simulate: bool):
    print(f"Connecting to {WS_URL}  (Ctrl+C to quit)")
    async with websockets.connect(WS_URL) as ws:
        print("Connected. Live events:\n")
        if simulate:
            await asyncio.sleep(0.5)
            await _simulate()
        while True:
            raw = await ws.recv()
            try:
                print(_format(json.loads(raw)))
            except json.JSONDecodeError:
                print(raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watch the WhatsApp live WebSocket stream.")
    parser.add_argument("--simulate", action="store_true", help="POST a fake inbound message after connecting")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.simulate))
    except KeyboardInterrupt:
        print("\nbye")
