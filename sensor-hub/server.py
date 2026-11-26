"""
SoldierIQ Sensor Hub - receives live sensor data and normalizes it for SoldierIQ.

Sensors are added in SoldierIQ (Connectors -> Sensors). The hub never decides
who may connect; it asks SoldierIQ.

  Phone (camera + GPS + compass)
      Admin adds a "Phone" sensor in SoldierIQ, which shows a QR code with
      https://<this-mac>:8443/phone?t=<pairing token>. The phone page streams
      camera frames (binary) and readings (JSON) over /ws/sensor. The hub checks
      the token with SoldierIQ before accepting anything.

  GPS tracker (any of Traccar's 200+ protocols, or the Traccar Client app)
      Admin adds a "GPS tracker" sensor with its device ID / IMEI. SoldierIQ
      registers it in Traccar. The hub polls Traccar for new positions, maps the
      device ID back to the SoldierIQ sensor, normalizes and forwards.

Every reading becomes ONE common envelope:

    {"v": 1, "sensor_id": "sen_...", "sensor_type": "phone" | "gps_tracker",
     "kind": "position" | "orientation" | "motion" | "status" | "connected" | "disconnected",
     "ts": <sensor time ms>, "received_ts": <hub time ms>, "data": {...fixed fields/units...}}

and is pushed to SoldierIQ (POST /api/sensors/internal/readings) about once a
second. Camera video stays here; SoldierIQ gives browsers a signed URL to
/api/sensors/{id}/stream.mjpg.

Listeners (same state):
  local mode:  https://0.0.0.0:8443   phones on the LAN: /phone, /ws/sensor, signed video URLs only
               http://127.0.0.1:8090  this machine: everything (SoldierIQ backend, debug viewer at /)
  cloud mode (PORT set, e.g. Railway): one listener on $PORT behind the platform's HTTPS; anything
               beyond the phone page / signed video needs the X-Sensor-Hub-Secret header.

Camera alerts: cameras with "watch" on (rules set in SoldierIQ) are checked by a
decision model (Perplexity Decider v1.2 via OpenRouter); only alerts reach SoldierIQ.

Config (.env next to this file): SENSOR_HUB_SECRET, SOLDIERIQ_API_URL,
TRACCAR_URL, TRACCAR_USER, TRACCAR_PASSWORD, OPENROUTER_API_KEY, and for SoldierIQ's own decision
model DECIDE_URL + DECIDE_API_KEY (the decide-service).

IP cameras (CCTV): SoldierIQ lists the cameras to pull (/internal/cameras, RTSP address with
login). For each one, ffmpeg reads the RTSP stream and hands the hub a few JPEG frames per second;
from there a camera is treated exactly like a phone camera (live view, alerts). The hub must be able
to reach the camera, so for a camera on a private network run the hub on that network. Needs ffmpeg.
CAMERA_FPS (default 2) and CAMERA_WIDTH (default 960) set what is read from each camera.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import shutil
import socket
import struct
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

BASE = Path(__file__).parent
STATIC = BASE / "static"
CERTS = BASE / "certs"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(BASE / ".env")

SECRET = os.environ.get("SENSOR_HUB_SECRET", "")
SOLDIERIQ_API_URL = os.environ.get("SOLDIERIQ_API_URL", "http://127.0.0.1:8010").rstrip("/")
TRACCAR_URL = os.environ.get("TRACCAR_URL", "http://127.0.0.1:8082").rstrip("/")
TRACCAR_USER = os.environ.get("TRACCAR_USER", "")
TRACCAR_PASSWORD = os.environ.get("TRACCAR_PASSWORD", "")
HTTPS_PORT = int(os.environ.get("HUB_HTTPS_PORT", "8443"))
HTTP_PORT = int(os.environ.get("HUB_HTTP_PORT", "8090"))
# Cloud mode (Railway etc.): the platform sets PORT and terminates HTTPS. One plain-HTTP listener,
# no self-signed cert; trust comes only from the shared secret / signed links, never from the port.
CLOUD_PORT = int(os.environ["PORT"]) if os.environ.get("PORT") else None
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")          # e.g. https://sensor-hub.up.railway.app
TRACKER_HOST = os.environ.get("TRACKER_HOST", "")                  # host GPS trackers send to (Traccar)
STALE_AFTER_S = 5.0
CAMERA_TYPES = ("phone", "ip_camera")
KNOTS_TO_MPS = 0.514444

app = FastAPI(title="SoldierIQ Sensor Hub")
_http: httpx.AsyncClient | None = None


def now_ms() -> int:
    return int(time.time() * 1000)


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


# ---------------------------------------------------------------- SoldierIQ link

async def soldieriq(path: str, payload: dict) -> tuple[int, dict | None]:
    try:
        r = await _http.post(f"{SOLDIERIQ_API_URL}/api/sensors{path}", json=payload,
                             headers={"X-Sensor-Hub-Secret": SECRET}, timeout=30)
        return r.status_code, (r.json() if r.content else None)
    except (httpx.HTTPError, ValueError) as e:
        log(f"SoldierIQ unreachable ({path}): {type(e).__name__} {e}")
        return 0, None


_IDENT_CACHE: dict[str, tuple[float, dict | None]] = {}


class Unreachable(Exception):
    """SoldierIQ could not be asked; retry later instead of dropping data."""


async def resolve_identifier(identifier: str) -> dict | None:
    hit = _IDENT_CACHE.get(identifier)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    code, body = await soldieriq("/internal/resolve", {"identifier": identifier})
    if code == 0 or code >= 500:
        if hit:  # SoldierIQ briefly down: keep using what we knew
            return hit[1]
        raise Unreachable(identifier)
    info = body if code == 200 else None
    _IDENT_CACHE[identifier] = (time.time(), info)
    return info


OUTBOX: deque[dict] = deque(maxlen=5000)
LATEST_ORIENTATION: dict[str, dict] = {}


def forward(env: dict) -> None:
    """Queue a reading for SoldierIQ. Orientation is coalesced; motion stays local."""
    if env["kind"] == "motion":
        return
    if env["kind"] in ("orientation", "detection"):  # only the newest matters
        LATEST_ORIENTATION[f'{env["sensor_id"]}:{env["kind"]}'] = env
    else:
        OUTBOX.append(env)


async def forwarder() -> None:
    while True:
        await asyncio.sleep(1.0)
        batch = list(OUTBOX) + list(LATEST_ORIENTATION.values())
        if not batch:
            continue
        OUTBOX.clear()
        LATEST_ORIENTATION.clear()
        code, _ = await soldieriq("/internal/readings", {"events": batch[-2000:]})
        if code != 200:
            # keep them for the next try (deque maxlen drops the oldest if SoldierIQ stays down)
            OUTBOX.extend(e for e in batch[-2000:] if e["kind"] not in ("orientation", "detection"))
            if code:
                log(f"SoldierIQ rejected readings ({code})")


# ---------------------------------------------------------------- normalization

def _num(v, digits: int | None = None):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(f, digits) if digits is not None else f


def envelope(sensor: "Sensor", kind: str, data: dict, ts=None, received_ts=None) -> dict:
    return {
        "v": 1, "sensor_id": sensor.id, "sensor_type": sensor.type, "kind": kind,
        "ts": int(ts) if isinstance(ts, (int, float)) else now_ms(),
        "received_ts": int(received_ts) if received_ts else now_ms(),
        "data": data,
    }


def normalize_phone(sensor: "Sensor", raw: dict) -> dict | None:
    kind = raw.get("kind")
    d = raw.get("data") or {}
    if kind == "position":
        lat, lon = _num(d.get("lat"), 7), _num(d.get("lon"), 7)
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        data = {"lat": lat, "lon": lon, "accuracy_m": _num(d.get("accuracy"), 1), "alt_m": _num(d.get("altitude"), 1),
                "course_deg": _num(d.get("heading"), 1), "speed_mps": _num(d.get("speed"), 2)}
    elif kind == "orientation":
        data = {"heading_deg": _num(d.get("heading"), 1), "heading_source": d.get("headingSource"),
                "pitch_deg": _num(d.get("beta"), 1), "roll_deg": _num(d.get("gamma"), 1)}
    elif kind == "motion":
        a, r = d.get("accel") or {}, d.get("rotation") or {}
        data = {"accel_mps2": {k: _num(a.get(k), 3) for k in ("x", "y", "z")},
                "rotation_dps": {k: _num(r.get(k), 2) for k in ("alpha", "beta", "gamma")}}
    elif kind == "status":
        data = {"battery_pct": _num(d.get("battery"), 0), "charging": d.get("charging"), "camera": d.get("camera"),
                "resolution": d.get("resolution"), "target_fps": _num(d.get("fps"))}
    else:
        return None
    return envelope(sensor, kind, data, ts=raw.get("ts"))


def _iso_ms(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def normalize_traccar(sensor: "Sensor", p: dict) -> list[dict]:
    lat, lon = _num(p.get("latitude"), 7), _num(p.get("longitude"), 7)
    if lat is None or lon is None:
        return []
    ts, rx = _iso_ms(p.get("fixTime")), _iso_ms(p.get("serverTime"))
    speed = _num(p.get("speed"))
    out = [envelope(sensor, "position", {
        "lat": lat, "lon": lon,
        "accuracy_m": _num(p.get("accuracy"), 1) or None,
        "alt_m": _num(p.get("altitude"), 1),
        "course_deg": _num(p.get("course"), 1),
        "speed_mps": round(speed * KNOTS_TO_MPS, 2) if speed is not None else None,
        "valid_fix": p.get("valid"),
        "protocol": p.get("protocol"),
    }, ts=ts, received_ts=rx)]
    attrs = p.get("attributes") or {}
    if "batteryLevel" in attrs or "charge" in attrs:
        out.append(envelope(sensor, "status", {"battery_pct": _num(attrs.get("batteryLevel"), 0),
                                               "charging": attrs.get("charge")}, ts=ts, received_ts=rx))
    return out


# ---------------------------------------------------------------- state

class Sensor:
    def __init__(self, sensor_id: str, sensor_type: str, name: str, org: str):
        self.id, self.type, self.name, self.org = sensor_id, sensor_type, name, org
        self.client = None
        self.connected = True
        self.connected_at = self.last_seen = now_ms()
        self.latest: dict[str, dict] = {}
        self.frame: bytes | None = None
        self.frame_ts = self.frame_count = 0
        self.frame_captured_ts = 0
        self.uplink_ms: float | None = None
        self._frame_times: deque[float] = deque(maxlen=30)
        self._frame_event = asyncio.Event()

    @property
    def fps(self) -> float:
        t = self._frame_times
        if len(t) < 2 or time.time() - t[-1] > STALE_AFTER_S or t[-1] <= t[0]:
            return 0.0
        return round((len(t) - 1) / (t[-1] - t[0]), 1)

    def put_frame(self, data: bytes) -> None:
        # Phone page sends 8-byte capture time + JPEG; plain JPEG (starts FF D8) is accepted too.
        captured = None
        if len(data) > 10 and data[:2] != b"\xff\xd8":
            captured = struct.unpack("<d", data[:8])[0]
            data = data[8:]
        self.frame, self.frame_ts = data, now_ms()
        self.frame_captured_ts = int(captured) if captured else self.frame_ts
        if captured:  # phone -> hub delay (phone and Mac clocks are both network-synced)
            d = max(0.0, self.frame_ts - captured)
            self.uplink_ms = d if self.uplink_ms is None else 0.8 * self.uplink_ms + 0.2 * d
        self.frame_count += 1
        self.last_seen = self.frame_ts
        self._frame_times.append(time.time())
        ev, self._frame_event = self._frame_event, asyncio.Event()
        ev.set()

    async def next_frame(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._frame_event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def summary(self) -> dict:
        window = STALE_AFTER_S * 1000 if self.type in CAMERA_TYPES else 600_000
        live = self.connected and (now_ms() - self.last_seen) < window
        return {
            "sensor_id": self.id, "sensor_type": self.type, "name": self.name, "client": self.client,
            "status": "live" if live else ("stale" if self.connected else "offline"),
            "connected_at": self.connected_at, "last_seen": self.last_seen,
            "camera": {"fps": self.fps, "frames": self.frame_count, "last_frame_ts": self.frame_ts or None,
                       "uplink_delay_ms": round(self.uplink_ms) if self.uplink_ms is not None else None,
                       "frame_bytes": len(self.frame) if self.frame else 0} if self.type in CAMERA_TYPES else None,
            "latest": self.latest,
            "watch": {k: _watch_state[self.id][k] for k in ("sent", "skipped")} if self.id in _watch_state else None,
        }


SENSORS: dict[str, Sensor] = {}
CONNECTIONS: dict[str, WebSocket] = {}
EVENTS: deque[dict] = deque(maxlen=500)
SUBSCRIBERS: set[asyncio.Queue] = set()


def publish(env: dict) -> None:
    """Local fan-out (debug viewer) + queue for SoldierIQ."""
    if env["kind"] != "motion":
        EVENTS.append(env)
    for q in list(SUBSCRIBERS):
        if q.qsize() < 200:
            q.put_nowait(env)
    forward(env)


# ---------------------------------------------------------------- access control

def is_local(scope) -> bool:
    """Request came in on the localhost-only listener (local mode only; never true in cloud mode)."""
    if CLOUD_PORT:
        return False
    server = scope.get("server") or ("", 0)
    return server[1] == HTTP_PORT


def has_secret(headers, query=None) -> bool:
    given = headers.get("x-sensor-hub-secret", "") or ((query or {}).get("key") or "")
    return bool(SECRET) and hmac.compare_digest(given, SECRET)


def trusted(request) -> bool:
    """SoldierIQ backend or this machine: the localhost listener, or the shared secret."""
    return is_local(request.scope) or has_secret(request.headers)


def signed_ok(sensor_id: str, exp: str | None, sig: str | None) -> bool:
    if not (SECRET and exp and sig and exp.isdigit()) or int(exp) < time.time():
        return False
    want = hmac.new(SECRET.encode(), f"{sensor_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig)


PUBLIC_PATHS = {"/phone", "/api/info", "/favicon.ico", "/health"}


@app.middleware("http")
async def lan_guard(request: Request, call_next):
    """Public listeners only serve the phone page and signed video URLs; the rest needs the secret."""
    if not trusted(request):
        path = request.url.path
        signed_video = path.startswith("/api/sensors/") and path.endswith(("/stream.mjpg", "/frame.jpg"))
        if path not in PUBLIC_PATHS and not signed_video:
            return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)


def check_internal(request: Request) -> None:
    if not has_secret(request.headers):
        raise HTTPException(401, "unauthorized")


# ---------------------------------------------------------------- phone ingest

@app.websocket("/ws/sensor")
async def ws_sensor(ws: WebSocket):
    await ws.accept()
    sensor: Sensor | None = None
    last_motion = 0.0
    try:
        hello = json.loads(await ws.receive_text())
        token = str(hello.get("token") or "")
        if hello.get("kind") != "hello" or not token:
            await ws.send_text(json.dumps({"kind": "error", "reason": "unpaired"}))
            await ws.close(code=4001)
            return
        code, info = await soldieriq("/internal/resolve", {"pairing_token": token})
        if code != 200 or not info or info.get("sensor_type") != "phone":
            reason = "soldieriq_unreachable" if code == 0 else "unpaired"
            await ws.send_text(json.dumps({"kind": "error", "reason": reason}))
            await ws.close(code=4001 if code else 1013)
            return
        if not info.get("enabled"):
            await ws.send_text(json.dumps({"kind": "error", "reason": "paused", "name": info["name"]}))
            await ws.close(code=4003)
            return

        sid = info["sensor_id"]
        old = CONNECTIONS.get(sid)
        if old is not None:  # same sensor opened on a second device/tab: newest wins
            try:
                await old.close(code=4004)
            except RuntimeError:
                pass
        sensor = SENSORS.get(sid) or Sensor(sid, "phone", info["name"], info["organization_id"])
        SENSORS[sid] = sensor
        sensor.name, sensor.client = info["name"], (ws.client.host if ws.client else "?")
        sensor.connected, sensor.connected_at, sensor.last_seen = True, now_ms(), now_ms()
        CONNECTIONS[sid] = ws
        publish(envelope(sensor, "connected", {"name": sensor.name, "client": sensor.client}))
        await ws.send_text(json.dumps({"kind": "welcome", "sensor_id": sid, "name": sensor.name, "server_ts": now_ms()}))
        log(f"phone connected: {sensor.name} ({sid}) from {sensor.client}")

        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                sensor.put_frame(msg["bytes"])
                continue
            if msg.get("text") is None:
                continue
            try:
                raw = json.loads(msg["text"])
            except json.JSONDecodeError:
                continue
            env = normalize_phone(sensor, raw)
            if env is None:
                continue
            sensor.latest[env["kind"]] = env
            sensor.last_seen = env["received_ts"]
            if env["kind"] == "motion":
                t = time.time()
                if t - last_motion < 0.25:
                    continue
                last_motion = t
            publish(env)
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
        pass
    finally:
        if sensor is not None and CONNECTIONS.get(sensor.id) is ws:
            CONNECTIONS.pop(sensor.id, None)
            sensor.connected = False
            publish(envelope(sensor, "disconnected", {"name": sensor.name}))
            log(f"phone disconnected: {sensor.name} ({sensor.id})")


@app.post("/internal/kick")
async def kick(request: Request):
    """SoldierIQ removed/paused/re-paired a sensor: drop its live connection now."""
    check_internal(request)
    sid = (await request.json()).get("sensor_id")
    ws = CONNECTIONS.get(sid)
    if ws is not None:
        try:
            await ws.send_text(json.dumps({"kind": "error", "reason": "removed"}))
            await ws.close(code=4002)
        except RuntimeError:
            pass
    _stop_camera(sid)
    s = SENSORS.pop(sid, None)
    for ident, (_, info) in list(_IDENT_CACHE.items()):
        if info and info.get("sensor_id") == sid:
            _IDENT_CACHE.pop(ident, None)
    return {"kicked": ws is not None, "known": s is not None}


# ---------------------------------------------------------------- Traccar (GPS trackers)

async def traccar_poller() -> None:
    if not TRACCAR_USER:
        log("Traccar not configured - GPS trackers disabled")
        return
    auth = (TRACCAR_USER, TRACCAR_PASSWORD)
    seen: dict[int, int] = {}  # traccar device id -> last forwarded position id
    warned = False
    while True:
        try:
            r = await _http.get(f"{TRACCAR_URL}/api/devices", auth=auth, timeout=10)
            r.raise_for_status()
            devices = {d["id"]: d for d in r.json()}
            changed = [d for d in devices.values() if d.get("positionId") and seen.get(d["id"]) != d["positionId"]]
            if changed:
                r = await _http.get(f"{TRACCAR_URL}/api/positions",
                                    params=[("id", d["positionId"]) for d in changed], auth=auth, timeout=10)
                r.raise_for_status()
                for p in r.json():
                    dev = devices.get(p.get("deviceId"))
                    if not dev:
                        continue
                    try:
                        info = await resolve_identifier(dev["uniqueId"])
                    except Unreachable:
                        continue  # not marked seen: picked up again on the next poll
                    seen[dev["id"]] = p["id"]
                    if not info or not info.get("enabled"):
                        continue
                    s = SENSORS.get(info["sensor_id"])
                    if s is None:
                        s = SENSORS[info["sensor_id"]] = Sensor(info["sensor_id"], "gps_tracker", info["name"],
                                                                info["organization_id"])
                    s.name, s.client, s.connected = info["name"], f"traccar:{p.get('protocol')}", True
                    for env in normalize_traccar(s, p):
                        s.latest[env["kind"]] = env
                        s.last_seen = env["received_ts"]
                        publish(env)
            warned = False
        except (httpx.HTTPError, ValueError, KeyError) as e:
            if not warned:
                log(f"Traccar poll failed: {e}")
                warned = True
        await asyncio.sleep(2.0)


# ---------------------------------------------------------------- IP cameras (CCTV)
#
# SoldierIQ says which cameras to pull and how (set by an org admin). A camera has one of three feed
# types, and all three end up calling Sensor.put_frame() with JPEG frames, so live view and alerts
# work the same no matter where the video came from:
#   rtsp      - an RTSP stream (Hikvision, Dahua/CP Plus, ...): ffmpeg reads it over TCP.
#   hls       - an HLS stream (.m3u8), the format most public/city cameras use: ffmpeg reads it.
#   snapshot  - a still-image URL that refreshes (e.g. a traffic cam that posts a JPEG): the hub just
#               fetches it on a timer. No ffmpeg needed, so these work even where ffmpeg is missing.
# A camera that drops is retried with a growing wait (2 s up to 30 s).

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
CAMERA_FPS = float(os.environ.get("CAMERA_FPS", "2"))
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "960"))
CAMERA_SILENCE_S = 20.0   # no frame for this long: the stream is stuck, reconnect
CAMERAS: dict[str, dict] = {}  # sensor_id -> {"task", "url"}


def _stop_camera(sid: str) -> None:
    cam = CAMERAS.pop(sid, None)
    if cam:
        cam["task"].cancel()


def _scrub(text: str, cfg: dict) -> str:
    """ffmpeg prints the address it failed on; never log or forward the login."""
    url = cfg.get("url") or ""
    password = urlsplit(url).password or ""
    for secret in (url, password, unquote(password)):
        if secret:
            text = text.replace(secret, "***")
    return text.strip()[-200:]


async def _jpeg_frames(stream: asyncio.StreamReader):
    """Split ffmpeg's MJPEG output into single JPEG images (FF D8 ... FF D9)."""
    buf = b""
    while True:
        chunk = await asyncio.wait_for(stream.read(65536), CAMERA_SILENCE_S)
        if not chunk:
            return
        buf += chunk
        while True:
            start = buf.find(b"\xff\xd8")
            if start < 0:
                buf = buf[-1:]
                break
            end = buf.find(b"\xff\xd9", start + 2)
            if end < 0:
                buf = buf[start:]
                break
            yield buf[start:end + 2]
            buf = buf[end + 2:]
        if len(buf) > 8_000_000:  # not a JPEG stream
            return


async def _ffmpeg_stream(cfg: dict):
    """Yield (jpeg, reason) from an RTSP or HLS stream via ffmpeg. reason is set only on a clean stop."""
    inp = ["-rtsp_transport", "tcp", "-i", cfg["url"]] if cfg["feed_type"] == "rtsp" else ["-i", cfg["url"]]
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-nostdin", "-loglevel", "error", *inp,
        "-an", "-vf", f"fps={CAMERA_FPS},scale='min({CAMERA_WIDTH},iw)':-2", "-q:v", "5",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    reason = "no video received"
    try:
        async for jpeg in _jpeg_frames(proc.stdout):
            yield jpeg, None
    except asyncio.TimeoutError:
        reason = f"no video for {CAMERA_SILENCE_S:.0f} s"
    finally:
        if proc.returncode is None:
            proc.kill()
        err = _scrub((await proc.stderr.read()).decode("utf-8", "replace"), cfg)
        await proc.wait()
        line = err.splitlines()[-1] if err else reason
        if "401" in line or "Unauthorized" in line or "403" in line:
            line = "the camera refused the username or password"
        elif "404" in line:
            line = "no stream at this address (check the brand, channel, path or URL)"
        elif any(x in line for x in ("refused", "timed out", "No route", "unreachable", "resolve", "Invalid data")):
            line = "the sensor hub could not reach the camera at this address"
        yield None, line


async def _snapshot_stream(cfg: dict):
    """Yield (jpeg, reason) by fetching a still-image URL on a timer (no ffmpeg)."""
    every = max(0.5, float(cfg.get("interval_s") or 1.0 / CAMERA_FPS))
    fails = 0
    while True:
        t = time.time()
        try:
            r = await _http.get(cfg["url"], timeout=10, follow_redirects=True)
            if r.status_code in (401, 403):
                yield None, "the camera refused the username or password"; return
            r.raise_for_status()
            body = r.content
            if not body.startswith(b"\xff\xd8"):
                yield None, "that URL did not return a JPEG image"; return
            fails = 0
            yield body, None
        except (httpx.HTTPError, ValueError):
            fails += 1
            if fails >= 3:
                yield None, "the sensor hub could not reach the image URL"; return
        await asyncio.sleep(max(0.0, every - (time.time() - t)))


async def camera_puller(sid: str, cfg: dict) -> None:
    sensor = SENSORS.get(sid)
    if sensor is None or sensor.type != "ip_camera":
        sensor = SENSORS[sid] = Sensor(sid, "ip_camera", cfg["name"], cfg["organization_id"])
    where = {"rtsp": cfg.get("host") or "?", "hls": "hls", "snapshot": "snapshot"}.get(cfg["feed_type"], "?")
    sensor.name, sensor.client, sensor.connected = cfg["name"], f"{cfg['feed_type']}:{where}", False
    source = _snapshot_stream if cfg["feed_type"] == "snapshot" else _ffmpeg_stream
    wait = 2.0
    try:
        while True:
            last_beat = 0.0
            reason = "no video received"
            async for jpeg, stop in source(cfg):
                if jpeg is None:
                    reason = stop or reason
                    break
                sensor.put_frame(jpeg)
                if not sensor.connected:
                    sensor.connected, sensor.connected_at, wait = True, now_ms(), 2.0
                    publish(envelope(sensor, "connected", {"name": sensor.name, "client": sensor.client}))
                    if cfg.get("lat") is not None and cfg.get("lon") is not None:  # fixed camera: its place on the map
                        env = envelope(sensor, "position", {"lat": cfg["lat"], "lon": cfg["lon"], "fixed": True})
                        sensor.latest["position"] = env
                        publish(env)
                    log(f"camera connected: {sensor.name} ({sid})")
                if time.time() - last_beat > 10:  # keeps "last seen" fresh in SoldierIQ
                    last_beat = time.time()
                    env = envelope(sensor, "status", {"streaming": True, "fps": sensor.fps})
                    sensor.latest["status"] = env
                    publish(env)
            was = sensor.connected
            sensor.connected = False
            publish(envelope(sensor, "disconnected", {"name": sensor.name, "reason": reason}))
            if was or wait == 2.0:
                log(f"camera stopped: {sensor.name} ({sid}): {reason}; retrying")
            await asyncio.sleep(wait)
            wait = min(30.0, wait * 2)
    finally:
        sensor.connected = False


async def camera_config_poller() -> None:
    have_ffmpeg = bool(shutil.which(FFMPEG))
    if not have_ffmpeg:
        log("ffmpeg not found - RTSP/HLS cameras disabled (install ffmpeg); snapshot cameras still work")
    while True:
        try:
            r = await _http.get(f"{SOLDIERIQ_API_URL}/api/sensors/internal/cameras",
                                headers={"X-Sensor-Hub-Secret": SECRET}, timeout=15)
            if r.status_code == 200:
                want = {}
                for c in r.json().get("cameras") or []:
                    if not c.get("url") or not c.get("feed_type"):
                        continue
                    if c["feed_type"] in ("rtsp", "hls") and not have_ffmpeg:
                        continue  # can't play a video stream without ffmpeg
                    want[c["sensor_id"]] = c
                for sid in list(CAMERAS):
                    if sid not in want or want[sid]["url"] != CAMERAS[sid]["url"]:
                        _stop_camera(sid)
                        if sid not in want:
                            SENSORS.pop(sid, None)
                for sid, cfg in want.items():
                    if sid not in CAMERAS or CAMERAS[sid]["task"].done():
                        CAMERAS[sid] = {"url": cfg["url"], "task": asyncio.create_task(camera_puller(sid, cfg))}
                    elif sid in SENSORS:
                        SENSORS[sid].name = cfg["name"]
        except (httpx.HTTPError, ValueError, KeyError):
            pass  # SoldierIQ briefly down: cameras already running keep running
        await asyncio.sleep(10)


# ---------------------------------------------------------------- camera watch (decision model)
#
# For each camera SoldierIQ says to watch, every `interval_s` the newest frame goes to a decision
# model with one yes/no question per alert
# rule the user configured ("Is a person visible?", "Is a bird visible?" ...). It returns calibrated
# probabilities, no text. Each camera picks its model (watch["model"]):
#   perplexity - Perplexity Decider v1.2 via OpenRouter's decisions API (cloud)
#   soldieriq  - SoldierIQ's own model (base d1-omni-600M, int8) in the decide-service, same API
# A rule fires when it is above its threshold in 2 of the last 3 checks
# (one odd frame does not alert), then stays quiet for ALERT_COOLDOWN_S. Only alerts go to SoldierIQ.

DECISIONS_URL = "https://openrouter.ai/api/v1/systemone"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
DECIDE_URL = os.environ.get("DECIDE_URL", "").rstrip("/")      # e.g. http://127.0.0.1:8095
DECIDE_API_KEY = os.environ.get("DECIDE_API_KEY", "")
SOLDIERIQ_MODEL = "soldieriq/decide-600m-colour-int8"
ALERT_COOLDOWN_S = float(os.environ.get("ALERT_COOLDOWN_S", "60"))
HIT_WINDOW_S = float(os.environ.get("HIT_WINDOW_S", "30"))  # how long a "yes" counts toward 2 of 3
WATCHES: dict[str, dict] = {}
WATCH_MODEL = {"name": os.environ.get("DECISION_MODEL", "perplexity/pplx-decider-v1.2")}
_watch_state: dict[str, dict] = {}  # sensor_id -> {"last": t, "busy": bool, "hits": {rule: deque}, "alerted": {rule: t}}


async def watch_config_poller() -> None:
    while True:
        try:
            r = await _http.get(f"{SOLDIERIQ_API_URL}/api/sensors/internal/watches",
                                headers={"X-Sensor-Hub-Secret": SECRET}, timeout=15)
            if r.status_code == 200:
                body = r.json()
                WATCHES.clear()
                WATCHES.update(body.get("watches") or {})
                WATCH_MODEL["name"] = body.get("model") or WATCH_MODEL["name"]
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(10)


class ModelUnavailable(Exception):
    """The camera's chosen decision model is not configured on this hub."""


def model_for(watch: dict) -> tuple[str, str, str]:
    """(url, api key, model name) for the decision model this camera uses."""
    if watch.get("model") == "soldieriq":
        if not DECIDE_URL:
            raise ModelUnavailable("SoldierIQ model chosen but DECIDE_URL is not set on the sensor hub")
        return f"{DECIDE_URL}/api/v1/systemone", DECIDE_API_KEY, SOLDIERIQ_MODEL
    if not OPENROUTER_API_KEY:
        raise ModelUnavailable("Perplexity chosen but OPENROUTER_API_KEY is not set on the sensor hub")
    return DECISIONS_URL, OPENROUTER_API_KEY, WATCH_MODEL["name"]


async def decide(jpeg: bytes, rules: list[dict], watch: dict | None = None) -> dict[str, float]:
    import base64
    url, key, model = model_for(watch or {})
    body = {
        "model": model,
        "state": [{"type": "text", "text": "Live security camera frame."},
                  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}],
        "questions": {r["id"]: {"type": "choice", "instructions": r["question"] + " Answer from the image only.",
                                "criteria": {"yes": "clearly visible in the image", "no": "not visible"}} for r in rules},
    }
    r = await _http.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    answers = r.json().get("answers") or {}
    return {k: float((v.get("probabilities") or {}).get("yes", 0)) for k, v in answers.items()}


async def _check(sensor: "Sensor", watch: dict, st: dict) -> None:
    jpeg, captured = sensor.frame, sensor.frame_captured_ts
    try:
        model = model_for(watch)[2]
        probs = await decide(jpeg, watch["rules"], watch)
    except (httpx.HTTPError, ValueError, ModelUnavailable) as e:
        if not st.get("warned"):
            log(f"decision model call failed for {sensor.name}: {type(e).__name__} {e}")
            st["warned"] = True
        return
    finally:
        st["busy"] = False
    st["warned"] = False
    rules = {r["id"]: r for r in watch["rules"]}
    publish(envelope(sensor, "detection", {"model": model, "probabilities":
                                           {rules[k]["label"]: round(p, 3) for k, p in probs.items() if k in rules}},
                     ts=captured))
    now = time.time()
    if any(p >= rules[k]["threshold"] and now - st["alerted"].get(k, 0) > ALERT_COOLDOWN_S
           for k, p in probs.items() if k in rules):
        st["active_until"] = now + MOTION_HOLD_S  # something new of interest: keep checking until confirmed
    for rid, p in probs.items():
        rule = rules.get(rid)
        if not rule:
            continue
        # Last 3 answers for this rule, as (time, above threshold). Answers older than HIT_WINDOW_S
        # don't count: a "yes" from before a cooldown or a quiet spell must not help fire a new alert.
        hits = st["hits"].setdefault(rid, deque(maxlen=3))
        hit = p >= rule["threshold"]
        hits.append((now, hit))
        fresh = sum(1 for t, h in hits if h and now - t <= HIT_WINDOW_S)
        # Fire only on a "yes" (so the alert's frame and probability show the thing), with 2 of 3 recent.
        if hit and fresh >= 2 and now - st["alerted"].get(rid, 0) > ALERT_COOLDOWN_S:
            st["alerted"][rid] = now
            hits.clear()  # the next alert needs new evidence
            asyncio.create_task(_send_alert(sensor, rule, p, captured, jpeg, model))


async def _send_alert(sensor: "Sensor", rule: dict, p: float, captured: int, jpeg: bytes, model: str) -> None:
    import base64
    log(f"ALERT {sensor.name}: {rule['label']} ({p:.2f})")
    code, _ = await soldieriq("/internal/alerts", {
        "sensor_id": sensor.id, "rule_id": rule["id"], "label": rule["label"], "probability": p,
        "model": model, "captured_ts": captured, "jpeg_b64": base64.b64encode(jpeg).decode()})
    if code != 200:
        log(f"alert not stored by SoldierIQ ({code})")


# Motion check: before paying for a model call, compare the frame with the last one the model saw
# (tiny grayscale thumbnail, no AI). Static scene -> skip. After a change, keep checking for
# MOTION_HOLD_S so the "2 of 3" rule can confirm; a heartbeat check still runs every HEARTBEAT_S.
MOTION_THRESHOLD = float(os.environ.get("MOTION_THRESHOLD", "6"))  # mean abs pixel change, 0-255
MOTION_HOLD_S = float(os.environ.get("MOTION_HOLD_S", "12"))
HEARTBEAT_S = float(os.environ.get("HEARTBEAT_S", "60"))


def _thumb(jpeg: bytes) -> bytes | None:
    from io import BytesIO

    from PIL import Image

    try:
        im = Image.open(BytesIO(jpeg))
        im.draft("L", (64, 64))  # JPEG decodes at 1/8 scale: ~1 ms
        return im.convert("L").resize((32, 24)).tobytes()
    except Exception:  # noqa: BLE001 - a bad frame just counts as "changed"
        return None


def _motion(a: bytes | None, b: bytes | None) -> float:
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


async def camera_watcher() -> None:
    if not OPENROUTER_API_KEY:
        log("OPENROUTER_API_KEY not set - cameras on the Perplexity model won't be checked")
    if not DECIDE_URL:
        log("DECIDE_URL not set - cameras on the SoldierIQ model won't be checked")
    while True:
        await asyncio.sleep(0.25)
        now = time.time()
        for sid, watch in list(WATCHES.items()):
            s = SENSORS.get(sid)
            if not watch.get("rules") or not s or not s.connected or not s.frame or now * 1000 - s.frame_ts > 5000:
                continue
            st = _watch_state.setdefault(sid, {"last": 0.0, "busy": False, "hits": {}, "alerted": {}, "ref": None,
                                               "active_until": 0.0, "last_sent": 0.0, "sent": 0, "skipped": 0})
            if st["busy"] or now - st["last"] < watch.get("interval_s", 3):
                continue
            st["last"] = now
            thumb = await asyncio.to_thread(_thumb, s.frame)
            change = _motion(thumb, st["ref"])
            if change >= MOTION_THRESHOLD:
                st["active_until"] = now + MOTION_HOLD_S
            if (watch.get("motion_only", True) and now >= st["active_until"]
                    and now - st["last_sent"] < HEARTBEAT_S):
                st["skipped"] += 1  # nothing moved: no model call
                continue
            st["ref"], st["last_sent"], st["busy"] = thumb, now, True
            st["sent"] += 1
            asyncio.create_task(_check(s, watch, st))


# ---------------------------------------------------------------- read API (local; video also via signed URL)

def _get(sensor_id: str) -> Sensor:
    s = SENSORS.get(sensor_id)
    if s is None:
        raise HTTPException(404, "unknown sensor")
    return s


def _video_access(request: Request, sensor_id: str) -> Sensor:
    if not trusted(request) and not signed_ok(sensor_id, request.query_params.get("exp"),
                                                     request.query_params.get("sig")):
        raise HTTPException(403, "invalid or expired link")
    return _get(sensor_id)


@app.get("/api/sensors")
def list_sensors():
    return {"sensors": [s.summary() for s in SENSORS.values()], "server_ts": now_ms()}


@app.get("/api/sensors/{sensor_id}")
def get_sensor(sensor_id: str):
    return _get(sensor_id).summary()


FRAME_HEADERS = {"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*",
                 "Access-Control-Expose-Headers": "X-Frame-Seq, X-Captured-Ts"}


@app.get("/api/sensors/{sensor_id}/frame.jpg")
async def latest_frame(sensor_id: str, request: Request, after: int = -1):
    """Newest frame. With ?after=<seq> it waits (up to 5 s) for a frame newer than seq, so a
    viewer can loop request -> show -> request and always see the latest frame, never a backlog."""
    s = _video_access(request, sensor_id)
    if after >= 0 and s.frame_count <= after:
        await s.next_frame(timeout=5)
    if not s.frame:
        raise HTTPException(404, "no frame yet")
    return Response(s.frame, media_type="image/jpeg", headers={
        **FRAME_HEADERS, "X-Frame-Seq": str(s.frame_count), "X-Captured-Ts": str(s.frame_captured_ts)})


@app.get("/api/sensors/{sensor_id}/stream.mjpg")
async def mjpeg(sensor_id: str, request: Request):
    s = _video_access(request, sensor_id)

    async def gen():
        if s.frame:
            yield _part(s.frame)
        while True:
            if await s.next_frame(timeout=10):
                yield _part(s.frame)
            elif not s.connected or SENSORS.get(sensor_id) is not s:
                return

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})


def _part(jpeg: bytes) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"


@app.get("/api/events")
def recent_events(limit: int = 100, sensor_id: str | None = None):
    ev = [e for e in EVENTS if sensor_id is None or e["sensor_id"] == sensor_id]
    return {"events": ev[-max(1, min(limit, 500)):]}


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    if not (is_local(ws.scope) or has_secret(ws.headers, ws.query_params)):
        await ws.close(code=4404)
        return
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    SUBSCRIBERS.add(q)
    try:
        await ws.send_text(json.dumps({"kind": "snapshot", "sensors": [s.summary() for s in SENSORS.values()]}))
        while True:
            await ws.send_text(json.dumps(await q.get()))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        SUBSCRIBERS.discard(q)


@app.get("/api/info")
def info():
    if CLOUD_PORT:
        return {"phone_url": f"{PUBLIC_URL}/phone" if PUBLIC_URL else None, "viewer_url": None,
                "lan_ip": TRACKER_HOST or None, "soldieriq_linked": bool(SECRET), "mode": "cloud"}
    ip = lan_ip()
    return {"phone_url": f"https://{ip}:{HTTPS_PORT}/phone", "viewer_url": f"http://localhost:{HTTP_PORT}/",
            "lan_ip": TRACKER_HOST or ip, "soldieriq_linked": bool(SECRET), "mode": "local"}


@app.get("/health")
def health():
    return {"ok": True, "sensors": len(SENSORS), "live": sum(1 for x in SENSORS.values() if x.connected)}


@app.get("/")
def viewer(request: Request):
    return FileResponse(STATIC / "index.html")


@app.get("/phone")
def phone():
    return FileResponse(STATIC / "phone.html", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- startup

def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_cert(ip: str) -> tuple[Path, Path]:
    """Self-signed cert for the current LAN IP (phones need HTTPS for camera/GPS)."""
    CERTS.mkdir(exist_ok=True)
    cert, key, stamp = CERTS / "cert.pem", CERTS / "key.pem", CERTS / "ip.txt"
    if cert.exists() and key.exists() and stamp.exists() and stamp.read_text().strip() == ip:
        return cert, key
    ipaddress.ip_address(ip)
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "825",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=SoldierIQ Sensor Hub",
        "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost",
    ], check=True, capture_output=True)
    stamp.write_text(ip)
    return cert, key


async def main() -> None:
    global _http
    if not SECRET:
        raise SystemExit("SENSOR_HUB_SECRET is not set (sensor-hub/.env) - it must match SoldierIQ's backend/.env")
    _http = httpx.AsyncClient()
    workers = (forwarder(), traccar_poller(), watch_config_poller(), camera_watcher(), camera_config_poller())
    if CLOUD_PORT:
        if not PUBLIC_URL:
            log("PUBLIC_URL is not set - SoldierIQ can't build phone pairing links")
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=CLOUD_PORT, log_level="warning",
                                               proxy_headers=True, forwarded_allow_ips="*"))
        print(f"\n  SoldierIQ Sensor Hub (cloud mode) on :{CLOUD_PORT}  public: {PUBLIC_URL or '?'}", flush=True)
        print(f"  SoldierIQ API -> {SOLDIERIQ_API_URL}\n", flush=True)
        await asyncio.gather(server.serve(), *workers)
        return
    ip = lan_ip()
    cert, key = ensure_cert(ip)
    https = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=HTTPS_PORT, ssl_certfile=str(cert),
                                          ssl_keyfile=str(key), log_level="warning"))
    http = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=HTTP_PORT, log_level="warning"))
    print("\n  SoldierIQ Sensor Hub", flush=True)
    print(f"  Phones   -> https://{ip}:{HTTPS_PORT}/phone?t=...  (QR code from SoldierIQ)", flush=True)
    print(f"  Trackers -> {ip}:5055 (Traccar Client app / OsmAnd), other ports per protocol", flush=True)
    print("  Cameras  -> IP cameras (RTSP) added in SoldierIQ are pulled from this machine", flush=True)
    print(f"  SoldierIQ API -> {SOLDIERIQ_API_URL}", flush=True)
    print(f"  Debug viewer  -> http://localhost:{HTTP_PORT}/\n", flush=True)
    await asyncio.gather(https.serve(), http.serve(), *workers)


if __name__ == "__main__":
    asyncio.run(main())
