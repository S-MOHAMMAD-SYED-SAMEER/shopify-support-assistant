"""Web chat for the support assistant.

Run locally:   uvicorn server:app --reload
Then open:     http://127.0.0.1:8000

Each browser chat gets its own SupportAgent, so the email + order lock and the
reply checks work exactly as in the terminal version. Limits below keep a public
demo from running up API costs.
"""
import os
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import SupportAgent
from shopify_client import ShopifyClient, load_env

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- limits for a public demo ----------
MAX_CHARS = 500            # longest customer message accepted
MAX_TURNS_PER_CHAT = 20    # messages in one chat
MAX_PER_IP_HOUR = 40       # messages per visitor per hour
MAX_PER_DAY = 400          # messages per day across everyone (cost cap)
MAX_CHATS = 200            # chats kept in memory; oldest dropped first
CHAT_IDLE_SECONDS = 30 * 60

env = load_env()
shop = ShopifyClient(env)                                  # one token cache for all chats
llm = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])

app = FastAPI(title="Shopify AI Support Assistant", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

_lock = threading.Lock()
_chats = OrderedDict()                 # chat_id -> {"agent", "turns", "last", "busy"}
_ip_hits = defaultdict(deque)          # ip -> times of recent messages
_day = {"date": time.strftime("%Y-%m-%d"), "count": 0}


class ChatIn(BaseModel):
    chat_id: str | None = None
    message: str


def _client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _check_limits(ip):
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    if _day["date"] != today:
        _day.update(date=today, count=0)
    if _day["count"] >= MAX_PER_DAY:
        raise HTTPException(429, "The demo has reached today's message limit. Please try again tomorrow.")
    hits = _ip_hits[ip]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= MAX_PER_IP_HOUR:
        raise HTTPException(429, "You've sent a lot of messages in the last hour. Please try again a bit later.")
    hits.append(now)
    _day["count"] += 1


def _get_chat(chat_id):
    now = time.time()
    for cid in [c for c, v in _chats.items() if now - v["last"] > CHAT_IDLE_SECONDS]:
        del _chats[cid]
    if chat_id and chat_id in _chats:
        _chats.move_to_end(chat_id)
        return chat_id, _chats[chat_id]
    while len(_chats) >= MAX_CHATS:
        _chats.popitem(last=False)
    cid = secrets.token_urlsafe(16)
    _chats[cid] = {"agent": SupportAgent(shop=shop, client=llm), "turns": 0, "last": now, "busy": False}
    return cid, _chats[cid]


def _steps(trace):
    """Readable 'behind the scenes' steps for one turn."""
    out = []
    for t in trace:
        if "tool" in t:
            args = dict(t.get("input") or {})
            if t["tool"] == "lookup_order":
                ok = "matched" if t.get("found") else "no match (number and email must both match)"
                out.append({"kind": "tool", "text": f"lookup_order {args.get('order_number', '')} + email → {ok}"})
            elif t["tool"] == "search_products":
                extra = f", max price {args['max_price']}" if args.get("max_price") is not None else ""
                out.append({"kind": "tool", "text": f"search_products \"{args.get('query', '')}\"{extra}"})
            elif t["tool"] == "get_policy":
                out.append({"kind": "tool", "text": f"get_policy {args.get('kind', '')}"})
            elif t["tool"] == "handoff_to_human":
                out.append({"kind": "handoff", "text": "AI handed off to a person"})
        elif t.get("check") == "pass":
            out.append({"kind": "pass", "text": "Code check passed: no unverified order or tracking numbers, no false action claims"})
        elif t.get("check") == "blocked":
            out.append({"kind": "blocked", "text": f"Code check BLOCKED the reply: {t.get('problem', '')}. Sent a hand-off instead."})
        elif t.get("check") == "forced_handoff":
            out.append({"kind": "handoff", "text": "Code rule: this request needs a person, so code handed it off"})
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(400, "Please type a message.")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Please keep messages under {MAX_CHARS} characters.")
    with _lock:
        _check_limits(_client_ip(request))
        cid, chat_state = _get_chat(body.chat_id)
        if chat_state["turns"] >= MAX_TURNS_PER_CHAT:
            raise HTTPException(429, "This chat has reached its message limit. Start a new chat to keep going.")
        if chat_state["busy"]:
            raise HTTPException(409, "Still answering your last message.")
        chat_state["busy"] = True
        chat_state["turns"] += 1
        chat_state["last"] = time.time()
    agent = chat_state["agent"]
    try:
        start_trace, before = len(agent.trace), agent.handoff_count
        t0 = time.time()
        reply = agent.reply(text)
        took = round(time.time() - t0, 1)
    except Exception:
        # The chat history may be half-written, so drop this chat; the page starts a fresh one.
        with _lock:
            _chats.pop(cid, None)
        # Never show stack traces or keys to visitors.
        raise HTTPException(502, "Sorry, something went wrong on our side. Please send your message again.")
    finally:
        chat_state["busy"] = False
    return {
        "chat_id": cid,
        "reply": reply,
        "handed_off": agent.handoff_count > before,
        "steps": _steps(agent.trace[start_trace:]),
        "seconds": took,
    }
