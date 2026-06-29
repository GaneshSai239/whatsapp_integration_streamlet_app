"""A simple WhatsApp-like chat UI built with Streamlit.

- Receiving: reads the live message feed (the same Redis feed the webhook +
  WebSocket use) and shows it as chat bubbles. Auto-refreshes every 2s.
- Sending:   type a message and it's sent through the running send API
  (POST /api/send/text). A template fallback is provided for chats that are
  outside WhatsApp's 24-hour customer-service window.

Run (app.py must be running on :8080):
    ./venv/bin/streamlit run what_stream_app.py
"""

import os
import time
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

import tracker  # shares the same Redis feed as the webhook / websocket

load_dotenv(Path(__file__).resolve().parent / ".env")

API_BASE = os.getenv("API_BASE", "http://localhost:8080")
DEFAULT_TEMPLATE = os.getenv("DEFAULT_TEMPLATE", "hello_world")

st.set_page_config(page_title="WhatsApp Demo", layout="wide")

CSS = """
<style>
.block-container {padding-top: 1.5rem;}
.chat-box {height: 62vh; overflow-y: auto; padding: 12px 16px;
           background:#0b141a; border-radius:10px; display:flex; flex-direction:column;}
.row {display:flex; margin:4px 0;}
.row.in {justify-content:flex-start;}
.row.out {justify-content:flex-end;}
.bubble {max-width:70%; padding:8px 12px; border-radius:10px; font-size:14px;
         line-height:1.35; color:#e9edef; word-wrap:break-word; white-space:pre-wrap;}
.bubble.in {background:#202c33; border-top-left-radius:2px;}
.bubble.out {background:#005c4b; border-top-right-radius:2px;}
.meta {font-size:10px; color:#8696a0; margin-top:3px; text-align:right;}
.status {align-self:center; color:#8696a0; font-size:11px; margin:6px 0;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def contact_of(msg: dict) -> str:
    return msg.get("from") or msg.get("to") or "unknown"


def load_threads() -> dict[str, list[dict]]:
    threads: dict[str, list[dict]] = {}
    for msg in tracker.get_messages(500):
        threads.setdefault(contact_of(msg), []).append(msg)
    return threads


def send_text(to: str, body: str):
    try:
        resp = requests.post(f"{API_BASE}/api/send/text", json={"to": to, "body": body}, timeout=30)
    except requests.RequestException as exc:
        return False, str(exc)
    try:
        data = resp.json()
    except ValueError:
        data = resp.text
    return resp.ok, data


def send_template(to: str, name: str, params: list[str]):
    try:
        resp = requests.post(
            f"{API_BASE}/api/send/template",
            json={"to": to, "name": name, "language": "en_US", "body_params": params},
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, str(exc)
    try:
        data = resp.json()
    except ValueError:
        data = resp.text
    return resp.ok, data


st_autorefresh(interval=2000, key="refresh")
threads = load_threads()

# --- Sidebar: contacts + new chat ---------------------------------------
st.sidebar.title("Chats")

# Persistent, manually-added numbers (newest on top, deduped).
st.session_state.setdefault("contacts", [])


def normalize(number: str) -> str:
    """Keep digits only so '+1 555...' and '1555...' match the webhook's 'from'."""
    return "".join(ch for ch in number if ch.isdigit())


def add_contact(number: str):
    number = normalize(number)
    if number and number not in st.session_state["contacts"]:
        st.session_state["contacts"].insert(0, number)
    if number:
        st.session_state["active"] = number


new_number = st.sidebar.text_input("Add a phone number", placeholder="15551234567")
if st.sidebar.button("Add number", use_container_width=True) and new_number.strip():
    add_contact(new_number)
    st.rerun()

st.sidebar.divider()

# Show manually-added numbers first (stacked), then any others seen in the feed.
feed_numbers = [n for n in sorted(threads.keys()) if n not in st.session_state["contacts"]]
all_contacts = st.session_state["contacts"] + feed_numbers

if "active" not in st.session_state and all_contacts:
    st.session_state["active"] = all_contacts[0]

if not all_contacts:
    st.sidebar.caption("No chats yet. Add a number above to start.")

for name in all_contacts:
    msgs = threads.get(name, [])
    preview = (msgs[-1].get("text") or msgs[-1].get("type") or "") if msgs else "no messages yet"
    is_active = st.session_state.get("active") == name
    label = f"{'> ' if is_active else ''}{name}\n{preview[:28]}"
    if st.sidebar.button(label, key=f"c_{name}", use_container_width=True):
        st.session_state["active"] = name
        st.rerun()

active = st.session_state.get("active")

# --- Main: conversation -------------------------------------------------
if not active:
    st.info("Start a new chat from the sidebar, or wait for an incoming message.")
    st.stop()

st.subheader(f"Chat with {active}")

bubbles = ['<div class="chat-box">']
for msg in threads.get(active, []):
    text = (msg.get("text") or "").replace("<", "&lt;").replace(">", "&gt;")
    stamp = time.strftime("%H:%M", time.localtime(msg.get("ts", time.time())))
    direction = msg.get("direction")
    if direction == "status":
        bubbles.append(f'<div class="status">{text}</div>')
    elif direction == "outbound":
        bubbles.append(f'<div class="row out"><div class="bubble out">{text}<div class="meta">{stamp}</div></div></div>')
    else:
        bubbles.append(f'<div class="row in"><div class="bubble in">{text}<div class="meta">{stamp}</div></div></div>')
bubbles.append("</div>")
st.markdown("\n".join(bubbles), unsafe_allow_html=True)

# --- Send box -----------------------------------------------------------
message = st.chat_input("Type a message")
if message:
    ok, data = send_text(active, message)
    if ok:
        st.toast("Sent")
        time.sleep(0.3)
        st.rerun()
    else:
        st.error(f"Send failed: {data}")
        st.caption(
            "If this is outside WhatsApp's 24h window, free-text is blocked. "
            "Use the template sender below."
        )

with st.expander("Send approved template (works outside the 24h window)"):
    tpl_name = st.text_input("Template name", value=DEFAULT_TEMPLATE)
    tpl_params = st.text_input("Body params (comma-separated)", value="")
    if st.button("Send template"):
        params = [p.strip() for p in tpl_params.split(",") if p.strip()]
        ok, data = send_template(active, tpl_name, params)
        if ok:
            st.success("Template sent")
            time.sleep(0.3)
            st.rerun()
        else:
            st.error(f"Template send failed: {data}")
