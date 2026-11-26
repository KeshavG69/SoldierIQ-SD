"""SoldierIQ decide-service: our own decision model behind an OpenRouter-style /systemone API.

Serves the base LiquidAI d1-omni-600M, int8 weight-only, from SoldierIQ's HF repo (see model.py). The
request and response match what the sensor hub already sends to OpenRouter's decisions API, so a camera
can switch between Perplexity and this model without the hub changing how it asks:

  POST /api/v1/systemone   (also /v1/systemone)
    {"model": "...", "state": [{"type": "text", "text": "..."},
                               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}],
     "questions": {"person": {"type": "choice", "instructions": "Is at least one person visible?",
                              "criteria": {"yes": "...", "no": "..."}}}}
  -> {"model": "soldieriq/d1-omni-600m-int8",
      "answers": {"person": {"type": "choice", "choice": "yes", "probabilities": {"yes": 0.97, "no": 0.03}}}}

A yes/no choice is asked as a `noul` (yes/no) question, which is how d1 was trained on images. Other
choice and score questions are passed through as they are. Images come only as data: URLs (the
service never fetches URLs). One request runs at a time; the model is the bottleneck anyway.

Env: PORT (default 8095), DECIDE_API_KEY (callers send "Authorization: Bearer <key>"; required in
production), HF_TOKEN (the model repo is private), MODEL_REPO, TORCH_THREADS.
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import io
import os
import threading
import time
from contextlib import asynccontextmanager

import torch
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from PIL import Image

from pathlib import Path


def _load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(Path(__file__).parent / ".env")

import model as M  # noqa: E402 - reads MODEL_REPO from the env loaded above

API_KEY = os.environ.get("DECIDE_API_KEY", "")
MAX_IMAGE_BYTES = 8_000_000
MAX_QUESTIONS = 16
STATE = {"model": None, "error": None, "loaded_at": None, "requests": 0, "busy_ms": 0.0}
_lock = threading.Lock()


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def _load() -> None:
    try:
        t = time.time()
        if os.environ.get("TORCH_THREADS"):
            torch.set_num_threads(int(os.environ["TORCH_THREADS"]))
        STATE["model"] = M.load()
        STATE["loaded_at"] = time.time()
        log(f"model loaded: {M.MODEL_REPO} in {time.time() - t:.0f}s, {torch.get_num_threads()} CPU threads")
    except Exception as e:  # noqa: BLE001 - reported on /health; the service stays up to say why
        STATE["error"] = f"{type(e).__name__}: {e}"
        log(f"model failed to load: {STATE['error']}")


@asynccontextmanager
async def lifespan(_app):
    if not API_KEY:
        log("DECIDE_API_KEY not set - anyone who can reach this service can use it")
    threading.Thread(target=_load, daemon=True).start()  # /health answers while the model loads
    yield


app = FastAPI(title="SoldierIQ decide-service", lifespan=lifespan)


@app.get("/health")
def health():
    ready = STATE["model"] is not None
    return {"ok": ready, "status": "ready" if ready else ("failed" if STATE["error"] else "loading"),
            "model": M.MODEL_NAME, "repo": M.MODEL_REPO, "error": STATE["error"],
            "requests": STATE["requests"],
            "avg_ms": round(STATE["busy_ms"] / STATE["requests"]) if STATE["requests"] else None}


def _image(part: dict) -> Image.Image:
    url = ((part.get("image_url") or {}).get("url")) if isinstance(part.get("image_url"), dict) else part.get("image_url")
    if not isinstance(url, str) or not url.startswith("data:image/") or ";base64," not in url:
        raise HTTPException(422, "images must be data:image/...;base64 URLs")
    raw = base64.b64decode(url.split(";base64,", 1)[1], validate=False)
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image too large")
    try:
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "could not read the image")


def _parse_state(state) -> tuple[str | None, list[Image.Image]]:
    if state is None or isinstance(state, (str, int, float, bool, dict)) and not isinstance(state, list):
        return (state if isinstance(state, str) else None), []
    texts, images = [], []
    for part in state:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            texts.append(str(part.get("text") or ""))
        elif isinstance(part, dict) and part.get("type") == "image_url":
            images.append(_image(part))
    return ("\n".join(t for t in texts if t) or None), images


def _is_yes_no(q: dict) -> bool:
    c = q.get("criteria")
    return q.get("type") == "choice" and isinstance(c, dict) and {k.lower() for k in c} == {"yes", "no"}


def _run(state_text, images, questions: dict) -> dict:
    asked, yes_no = {}, set()
    for qid, q in questions.items():
        if not isinstance(q, dict) or "instructions" not in q:
            raise HTTPException(422, f"question {qid!r} needs type and instructions")
        if _is_yes_no(q):
            asked[qid] = {"type": "noul", "instructions": q["instructions"]}
            yes_no.add(qid)
        else:
            asked[qid] = q
    with _lock, torch.inference_mode():
        try:
            out = STATE["model"].system_one(state_text, asked, images=images or None)
        except ValueError as e:
            raise HTTPException(422, str(e))
    answers = {}
    for qid, a in (out.get("answers") or {}).items():
        if a.get("type") == "noul":
            p = float(a["noul"])
            answers[qid] = {"type": "choice" if qid in yes_no else "noul", "choice": "yes" if p >= 0.5 else "no",
                            "probabilities": {"yes": p, "no": 1.0 - p}}
            if qid not in yes_no:
                answers[qid]["noul"] = p
        else:
            answers[qid] = a
    return answers


@app.post("/api/v1/systemone")
@app.post("/v1/systemone")
async def systemone(body: dict, authorization: str | None = Header(None)):
    if API_KEY and not hmac.compare_digest((authorization or "").removeprefix("Bearer ").strip(), API_KEY):
        raise HTTPException(401, "invalid API key")
    if STATE["model"] is None:
        raise HTTPException(503, "model is still loading" if not STATE["error"] else f"model failed to load: {STATE['error']}")
    questions = body.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise HTTPException(422, "questions must be a non-empty object")
    if len(questions) > MAX_QUESTIONS:
        raise HTTPException(422, f"at most {MAX_QUESTIONS} questions per request")
    state_text, images = _parse_state(body.get("state"))
    t = time.time()
    answers = await asyncio.to_thread(_run, state_text, images, questions)
    ms = (time.time() - t) * 1000
    STATE["requests"] += 1
    STATE["busy_ms"] += ms
    return {"model": M.MODEL_NAME, "answers": answers, "latency_ms": round(ms)}


if __name__ == "__main__":
    # Listen on IPv6 and IPv4 at once: Railway's private network (decide-service.railway.internal) is IPv6,
    # local callers use 127.0.0.1. IPV6_V6ONLY=0 makes the "::" socket dual-stack on Linux and macOS alike.
    import socket

    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", int(os.environ.get("PORT", "8095"))))
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
