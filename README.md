# WhatsApp Cloud API — Live Chat Demo

A small, self-contained demo that connects to the **WhatsApp Cloud API** and gives you:

- A **webhook** that receives incoming WhatsApp messages and delivery/read statuses.
- A **WebSocket** (`/ws`) that streams every event live to any connected client.
- A **send API** for text, template, and interactive (button) messages.
- A **WhatsApp-style chat UI** built with Streamlit — add numbers, switch between
  conversations, and send/receive messages in real time.

> This is a learning/demo project. It is not production-hardened.

---

## Architecture

```
WhatsApp user
   │
   ▼
Meta servers ──(Callback URL set in Meta dashboard)──► public tunnel (cloudflared/ngrok)
                                                          │
                                                          ▼
                                            FastAPI app  (app.py)
                                            ├─ /webhook        receive events   (tracker.py)
                                            ├─ /ws             live stream       (tracker.py)
                                            └─ /api/send/*     send messages     (send_message.py)
                                                          │
                                                          ▼
                                                 Redis (history + pub/sub)
                                                          │
                                                          ▼
                                          Streamlit chat UI (what_stream_app.py)
```

Redis is used both to store recent message history and as a pub/sub channel so the
webhook (writer) and the WebSocket (reader) stay decoupled.

---

## Project structure

| File                  | Purpose                                                            |
| --------------------- | ----------------------------------------------------------------- |
| `app.py`              | FastAPI entry point; wires the webhook, WebSocket, and send API.   |
| `tracker.py`          | Webhook ingestion (`GET`/`POST /webhook`) + WebSocket (`/ws`).     |
| `send_message.py`     | Send API: `/api/send/text`, `/api/send/template`, `/api/send/interactive`. |
| `what_stream_app.py`  | Streamlit chat UI (send + receive).                               |
| `web_run.py`          | Tiny CLI WebSocket client to watch the live stream.               |
| `requirements.txt`    | Python dependencies.                                              |
| `.env.example`        | Template for your local `.env` (copy and fill in).               |

---

## Prerequisites

- **Python 3.10+**
- **Redis** running locally (`redis-server`)
- A **Meta / WhatsApp Cloud API** app with a test phone number
  ([developers.facebook.com](https://developers.facebook.com/))
- A tunneling tool to expose your local webhook publicly, e.g.
  [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
  or [`ngrok`](https://ngrok.com/)

---

## Setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

# 2. Create a virtual environment and install deps
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure your credentials
cp .env.example .env
# then edit .env and fill in ACCESS_TOKEN, APP_SECRET, APP_ID,
# PHONE_NUMBER_ID, WABA_ID, and a VERIFY_TOKEN of your choosing
```

---

## Running

Make sure Redis is up first: `redis-server` (or `redis-server --daemonize yes`).

**1. Start the backend (webhook + WebSocket + send API):**

```bash
uvicorn app:app --host 0.0.0.0 --port 8080
```

- Health check: <http://localhost:8080/>
- Interactive API docs: <http://localhost:8080/docs>

**2. Start the chat UI (in a second terminal):**

```bash
streamlit run what_stream_app.py --server.port 8501
```

Open <http://localhost:8501>.

**3. (Optional) Watch the raw WebSocket stream from the CLI:**

```bash
python web_run.py            # watch live events
python web_run.py --simulate # also fire a fake inbound message for testing
```

---

## Connecting the Meta webhook

Incoming messages only arrive if Meta can reach your `/webhook` over the public internet.

1. Start a tunnel pointing at the backend:

   ```bash
   cloudflared tunnel --url http://localhost:8080
   ```

   Copy the generated `https://<something>.trycloudflare.com` URL.

2. In the Meta App Dashboard → **WhatsApp → Configuration → Webhook → Edit**:
   - **Callback URL:** `https://<something>.trycloudflare.com/webhook`
   - **Verify token:** the same value as `VERIFY_TOKEN` in your `.env`
   - Click **Verify and save**.

3. Subscribe to the **`messages`** field.

> Quick tunnels generate a **new URL each restart**, so you must re-paste the
> Callback URL whenever you restart the tunnel.

---

## API reference

| Method | Path                     | Body                                              |
| ------ | ------------------------ | ------------------------------------------------- |
| GET    | `/`                      | — (health/info)                                   |
| GET    | `/webhook`               | Meta verification handshake                       |
| POST   | `/webhook`               | Meta event delivery                               |
| WS     | `/ws`                    | Live event stream (JSON per message)              |
| POST   | `/api/send/text`         | `{ "to": "...", "body": "..." }`                  |
| POST   | `/api/send/template`     | `{ "to": "...", "name": "...", "language": "en_US", "body_params": [] }` |
| POST   | `/api/send/interactive`  | `{ "to": "...", "text": "...", "buttons": [{"id": "...", "title": "..."}] }` |

Example:

```bash
curl -X POST http://localhost:8080/api/send/text \
  -H "Content-Type: application/json" \
  -d '{"to": "15551234567", "body": "Hello from the demo!"}'
```

---

## Notes & limitations

- **24-hour window:** WhatsApp only allows free-form text within 24 hours of the
  user's last message. Outside that window you must use an approved **template**
  (the UI has a template sender for this).
- **Development mode:** while your app is in Development mode, only numbers with an
  assigned role (admin/developer/tester) can message it.
- **Signature validation** is warn-only by default. Set `STRICT_SIGNATURE=1` in
  `.env` to reject unsigned/invalid `POST`s (recommended once `APP_SECRET` is set).

---

## Security

- Never commit your real `.env`. It is git-ignored; only `.env.example` is tracked.
- If a token was ever committed, **rotate it** in the Meta dashboard.

---

## License

MIT — see `LICENSE` (add one if you want a specific license).
