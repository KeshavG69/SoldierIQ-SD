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
  https://0.0.0.0:8443   phones on the LAN: /phone, /ws/sensor, signed video URLs only
  http://127.0.0.1:8090  this machine: everything (SoldierIQ backend, debug viewer at /)

Config (.env next to this file): SENSOR_HUB_SECRET, SOLDIERIQ_API_URL,
TRACCAR_URL, TRACCAR_USER, TRACCAR_PASSWORD.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import struct
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path

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
STALE_AFTER_S = 5.0
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
    if env["kind"] == "orientation":
        LATEST_ORIENTATION[env["sensor_id"]] = env
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
            OUTBOX.extend(e for e in batch[-2000:] if e["kind"] != "orientation")
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
        window = STALE_AFTER_S * 1000 if self.type == "phone" else 600_000
        live = self.connected and (now_ms() - self.last_seen) < window
        return {
            "sensor_id": self.id, "sensor_type": self.type, "name": self.name, "client": self.client,
            "status": "live" if live else ("stale" if self.connected else "offline"),
            "connected_at": self.connected_at, "last_seen": self.last_seen,
            "camera": {"fps": self.fps, "frames": self.frame_count, "last_frame_ts": self.frame_ts or None,
                       "uplink_delay_ms": round(self.uplink_ms) if self.uplink_ms is not None else None,
                       "frame_bytes": len(self.frame) if self.frame else 0} if self.type == "phone" else None,
            "latest": self.latest,
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
    server = scope.get("server") or ("", 0)
    return server[1] == HTTP_PORT


def signed_ok(sensor_id: str, exp: str | None, sig: str | None) -> bool:
    if not (SECRET and exp and sig and exp.isdigit()) or int(exp) < time.time():
        return False
    want = hmac.new(SECRET.encode(), f"{sensor_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig)


PUBLIC_PATHS = {"/phone", "/api/info", "/favicon.ico"}


@app.middleware("http")
async def lan_guard(request: Request, call_next):
    """The LAN (HTTPS) listener only serves the phone page and signed video URLs."""
    if not is_local(request.scope):
        path = request.url.path
        signed_video = path.startswith("/api/sensors/") and path.endswith(("/stream.mjpg", "/frame.jpg"))
        if path not in PUBLIC_PATHS and not signed_video:
            return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)


def check_internal(request: Request) -> None:
    if not is_local(request.scope) or not SECRET or not hmac.compare_digest(
            request.headers.get("x-sensor-hub-secret", ""), SECRET):
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


# ---------------------------------------------------------------- read API (local; video also via signed URL)

def _get(sensor_id: str) -> Sensor:
    s = SENSORS.get(sensor_id)
    if s is None:
        raise HTTPException(404, "unknown sensor")
    return s


def _video_access(request: Request, sensor_id: str) -> Sensor:
    if not is_local(request.scope) and not signed_ok(sensor_id, request.query_params.get("exp"),
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
    if not is_local(ws.scope):
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
    ip = lan_ip()
    return {"phone_url": f"https://{ip}:{HTTPS_PORT}/phone", "viewer_url": f"http://localhost:{HTTP_PORT}/",
            "lan_ip": ip, "soldieriq_linked": bool(SECRET)}


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
    ip = lan_ip()
    cert, key = ensure_cert(ip)
    https = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=HTTPS_PORT, ssl_certfile=str(cert),
                                          ssl_keyfile=str(key), log_level="warning"))
    http = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=HTTP_PORT, log_level="warning"))
    print("\n  SoldierIQ Sensor Hub", flush=True)
    print(f"  Phones   -> https://{ip}:{HTTPS_PORT}/phone?t=...  (QR code from SoldierIQ)", flush=True)
    print(f"  Trackers -> {ip}:5055 (Traccar Client app / OsmAnd), other ports per protocol", flush=True)
    print(f"  SoldierIQ API -> {SOLDIERIQ_API_URL}", flush=True)
    print(f"  Debug viewer  -> http://localhost:{HTTP_PORT}/\n", flush=True)
    await asyncio.gather(https.serve(), http.serve(), forwarder(), traccar_poller())


if __name__ == "__main__":
    asyncio.run(main())
