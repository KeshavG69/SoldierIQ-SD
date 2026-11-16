"""
Sensors - live devices an organization adds to SoldierIQ.

Admin endpoints (org admins):
  POST   /api/sensors                         add a sensor (phone | gps_tracker); returns setup info
  PATCH  /api/sensors/{id}                    rename / pause / resume
  DELETE /api/sensors/{id}                    remove (also from Traccar, and disconnects it)
  POST   /api/sensors/{id}/pairing            new QR pairing link for a phone (old one stops working)

Member endpoints (anyone in the org):
  GET    /api/sensors                         sensors + status + latest readings
  GET    /api/sensors/{id}                    one sensor (+ recent positions)
  GET    /api/sensors/{id}/stream-url         short-lived signed URL for the live camera
  GET    /api/sensors/snapshots/{id}.jpg?s=   camera frame the chat agent looked at (signed link)

Internal (sensor hub -> backend, header X-Sensor-Hub-Secret):
  POST   /api/sensors/internal/resolve        pairing token / tracker ID -> sensor
  POST   /api/sensors/internal/readings       normalized readings to store
  GET    /api/sensors/internal/watches        cameras to run the decision model on (+ their alert rules)
  POST   /api/sensors/internal/alerts         decision model fired: store the alert + frame

Alerts (camera watch, anyone in the org):
  GET    /api/sensors/alerts?since=&sensor_id=   newest alerts
  GET    /api/sensors/alerts/{id}.jpg?s=         the frame that triggered it (signed link)
  POST   /api/sensors/alerts/{id}/ack            mark as seen

Data path: phone / GPS tracker -> sensor hub (+ Traccar for trackers) -> normalized
readings -> here. Camera video stays on the hub; the browser loads it with a signed URL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.logger import logger
from app.settings import settings
from clients import traccar_client
from orgs.dependencies import get_current_context, require_org_admin
from utils import sensor_store

router = APIRouter(prefix="/sensors", tags=["sensors"])

LIVE_WINDOW_S = {"phone": 20, "gps_tracker": 600}
STREAM_URL_TTL_S = 3600
_IDENT_RE = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")

_hub_info: Dict[str, Any] = {}
_hub_info_at = 0.0


# ---------------------------------------------------------------- helpers

def _org(ctx: dict) -> str:
    org = ctx.get("organization_id")
    if not org:
        raise HTTPException(403, "No active organization")
    return org


def _require_enabled() -> None:
    if not settings.SENSOR_HUB_SECRET:
        raise HTTPException(503, "Sensors are not configured on this server (SENSOR_HUB_SECRET)")


async def _hub(method: str, path: str, **kw) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(base_url=settings.SENSOR_HUB_URL.rstrip("/"), timeout=5) as c:
            r = await c.request(method, path, headers={"X-Sensor-Hub-Secret": settings.SENSOR_HUB_SECRET}, **kw)
        return r.json() if r.status_code < 400 else None
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"[sensors] hub {path} failed: {e}")
        return None


async def _get_hub_info() -> Dict[str, Any]:
    global _hub_info, _hub_info_at
    if not _hub_info or time.time() - _hub_info_at > 60:
        info = await _hub("GET", "/api/info")
        if info:
            _hub_info, _hub_info_at = info, time.time()
    return _hub_info


def _status(s: dict) -> str:
    if not s["enabled"]:
        return "paused"
    if not s["last_seen"]:
        return "waiting"
    conn = (s.get("latest") or {}).get("connection") or {}
    if s["sensor_type"] == "phone" and conn.get("kind") == "disconnected":
        return "offline"
    age = (datetime.now(timezone.utc) - s["last_seen"]).total_seconds()
    return "live" if age < LIVE_WINDOW_S.get(s["sensor_type"], 60) else "offline"


async def _setup(s: dict) -> Dict[str, Any]:
    info = await _get_hub_info()
    if s["sensor_type"] == "phone":
        base = info.get("phone_url")
        return {"pair_url": f"{base}?t={s['pairing_token']}" if base and s.get("pairing_token") else None,
                "hub_reachable": bool(base)}
    host = info.get("lan_ip")
    return {
        "server_host": host,
        "server_port": settings.TRACCAR_OSMAND_PORT,
        "server_url": f"http://{host}:{settings.TRACCAR_OSMAND_PORT}" if host else None,
        "device_id": s["identifier"],
        "hub_reachable": bool(host),
    }


async def _public(s: dict, admin: bool) -> Dict[str, Any]:
    latest = s.get("latest") or {}
    out = {
        "id": s["id"],
        "name": s["name"],
        "sensor_type": s["sensor_type"],
        "identifier": s["identifier"],
        "enabled": s["enabled"],
        "status": _status(s),
        "last_seen": s["last_seen"].isoformat() if s["last_seen"] else None,
        "created_at": s["created_at"].isoformat(),
        "has_camera": s["sensor_type"] == "phone",
        "latest": {k: latest[k] for k in ("position", "orientation", "status", "detection") if k in latest},
        "watch": sensor_store.normalize_watch(s.get("watch")) if s["sensor_type"] == "phone" else None,
    }
    if admin:
        out["setup"] = await _setup(s)
    return out


def _sign(sensor_id: str, exp: int) -> str:
    return hmac.new(settings.SENSOR_HUB_SECRET.encode(), f"{sensor_id}.{exp}".encode(), hashlib.sha256).hexdigest()


async def _kick(sensor_id: str) -> None:
    await _hub("POST", "/internal/kick", json={"sensor_id": sensor_id})


# ---------------------------------------------------------------- camera snapshots (chat replies)

@router.get("/snapshots/{snap_file}")
async def snapshot(snap_file: str, s: str = "") -> Response:
    """A camera frame the chat agent looked at (look_at_camera). Signed link, so it works in <img>."""
    from utils.sensor_tools import load_snapshot, snapshot_sig_ok

    snap_id = snap_file.removesuffix(".jpg")
    if not snapshot_sig_ok(snap_id, s):
        raise HTTPException(403, "Invalid link")
    snap = await load_snapshot(snap_id)
    if not snap:
        raise HTTPException(404, "Snapshot expired")
    return Response(base64.b64decode(snap["jpeg_b64"]), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


# ---------------------------------------------------------------- alerts (camera watch)

def _alert_sig(alert_id: str) -> str:
    return hmac.new(settings.SENSOR_HUB_SECRET.encode(), f"alert.{alert_id}".encode(), hashlib.sha256).hexdigest()[:20]


def alert_image_url(alert_id: str) -> str:
    return f"{settings.PUBLIC_API_URL.rstrip('/')}/api/sensors/alerts/{alert_id}.jpg?s={_alert_sig(alert_id)}"


def alert_public(a: dict) -> Dict[str, Any]:
    return {
        "id": a["id"], "sensor_id": a["sensor_id"], "sensor_name": a["sensor_name"], "rule_id": a["rule_id"],
        "label": a["label"], "probability": round(a["probability"] or 0, 3), "model": a["model"],
        "captured_at": a["captured_at"].isoformat(), "created_at": a["created_at"].isoformat(),
        "lat": a["lat"], "lon": a["lon"], "heading": a["heading"],
        "acknowledged": a["acknowledged_at"] is not None,
        "image_url": alert_image_url(a["id"]),
    }


@router.get("/alerts")
async def list_alerts(since: Optional[str] = None, sensor_id: Optional[str] = None, limit: int = 30,
                      ctx: dict = Depends(get_current_context)) -> Dict[str, Any]:
    _require_enabled()
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since must be an ISO timestamp")
    rows = await sensor_store.list_alerts(_org(ctx), since=since_dt, sensor_id=sensor_id, limit=limit)
    return {"alerts": [alert_public(a) for a in rows], "server_time": datetime.now(timezone.utc).isoformat()}


@router.get("/alerts/{alert_file}")
async def alert_image(alert_file: str, s: str = "") -> Response:
    """The frame that triggered an alert. Signed link, so it works in <img>."""
    alert_id = alert_file.removesuffix(".jpg")
    if not settings.SENSOR_HUB_SECRET or not hmac.compare_digest(_alert_sig(alert_id), s or ""):
        raise HTTPException(403, "Invalid link")
    jpeg = await sensor_store.alert_snapshot(alert_id)
    if not jpeg:
        raise HTTPException(404, "No image")
    return Response(bytes(jpeg), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/alerts/{alert_id}/ack")
async def acknowledge(alert_id: str, ctx: dict = Depends(get_current_context)) -> Dict[str, Any]:
    _require_enabled()
    ok = await sensor_store.acknowledge_alert(alert_id, _org(ctx), ctx["id"])
    return {"acknowledged": ok}


# ---------------------------------------------------------------- member endpoints

@router.get("")
async def list_sensors(ctx: dict = Depends(get_current_context)) -> Dict[str, Any]:
    _require_enabled()
    admin = ctx.get("role") == "admin"
    rows = await sensor_store.list_sensors(_org(ctx))
    return {"sensors": [await _public(s, admin) for s in rows], "is_admin": admin}


@router.get("/{sensor_id}")
async def get_sensor(sensor_id: str, ctx: dict = Depends(get_current_context)) -> Dict[str, Any]:
    _require_enabled()
    org = _org(ctx)
    s = await sensor_store.get_sensor(sensor_id, org)
    if not s:
        raise HTTPException(404, "Sensor not found")
    out = await _public(s, ctx.get("role") == "admin")
    out["recent_positions"] = await sensor_store.recent_positions(sensor_id, org, limit=100)
    return out


@router.get("/{sensor_id}/stream-url")
async def stream_url(sensor_id: str, ctx: dict = Depends(get_current_context)) -> Dict[str, Any]:
    _require_enabled()
    s = await sensor_store.get_sensor(sensor_id, _org(ctx))
    if not s:
        raise HTTPException(404, "Sensor not found")
    if s["sensor_type"] != "phone":
        raise HTTPException(400, "This sensor has no camera")
    exp = int(time.time()) + STREAM_URL_TTL_S
    q = f"exp={exp}&sig={_sign(sensor_id, exp)}"
    base = f"{settings.SENSOR_HUB_VIEW_URL.rstrip('/')}/api/sensors/{sensor_id}"
    return {"stream_url": f"{base}/stream.mjpg?{q}", "frame_url": f"{base}/frame.jpg?{q}", "expires": exp}


# ---------------------------------------------------------------- admin endpoints

class CreateSensor(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    sensor_type: Literal["phone", "gps_tracker"]
    identifier: Optional[str] = Field(None, description="GPS tracker device ID / IMEI; generated if empty")


class WatchRule(BaseModel):
    id: Optional[str] = None
    label: str = Field(..., min_length=1, max_length=40, description="What to alert on, e.g. 'Person', 'Bird'")
    question: Optional[str] = Field(None, max_length=200, description="Precise yes/no question for the model")
    threshold: Optional[float] = Field(None, ge=0.5, le=0.99)


class WatchConfig(BaseModel):
    enabled: bool = False
    interval_s: Optional[float] = Field(None, ge=1, le=30)
    rules: Optional[List[WatchRule]] = Field(None, max_length=12)


class UpdateSensor(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    enabled: Optional[bool] = None
    watch: Optional[WatchConfig] = None


@router.post("", status_code=201)
async def create_sensor(body: CreateSensor, ctx: dict = Depends(require_org_admin)) -> Dict[str, Any]:
    _require_enabled()
    org, name = _org(ctx), body.name.strip()
    if not name:
        raise HTTPException(422, "Name is required")

    if body.sensor_type == "phone":
        s = await sensor_store.create_sensor(organization_id=org, name=name, sensor_type="phone",
                                             created_by=ctx["id"], pairing_token=sensor_store.new_pairing_token())
    else:
        ident = (body.identifier or "").strip()
        if ident:
            if not _IDENT_RE.match(ident):
                raise HTTPException(422, "Device ID must be 3-40 letters, digits, '-', '_' or '.'")
        else:
            ident = sensor_store.new_tracker_identifier()
            while await sensor_store.identifier_taken(ident):
                ident = sensor_store.new_tracker_identifier()
        if await sensor_store.identifier_taken(ident):
            raise HTTPException(409, "A sensor with this device ID already exists")
        try:
            device_id = await traccar_client.create_device(name, ident)
        except traccar_client.TraccarError as e:
            logger.error(f"[sensors] {e}")
            raise HTTPException(502, "Could not register the tracker with the GPS server. Is Traccar running?")
        try:
            s = await sensor_store.create_sensor(organization_id=org, name=name, sensor_type="gps_tracker",
                                                 created_by=ctx["id"], identifier=ident, traccar_device_id=device_id)
        except Exception:
            await traccar_client.delete_device(device_id)
            raise
    logger.info(f"[sensors] {ctx['id']} added {s['sensor_type']} {s['id']} to org {org}")
    return await _public(s, admin=True)


@router.patch("/{sensor_id}")
async def update_sensor(sensor_id: str, body: UpdateSensor, ctx: dict = Depends(require_org_admin)) -> Dict[str, Any]:
    _require_enabled()
    org = _org(ctx)
    s = await sensor_store.get_sensor(sensor_id, org)
    if not s:
        raise HTTPException(404, "Sensor not found")
    fields: Dict[str, Any] = {}
    if body.name is not None and body.name.strip():
        fields["name"] = body.name.strip()
    if body.enabled is not None:
        fields["enabled"] = body.enabled
    s = await sensor_store.update_sensor(sensor_id, org, **fields)
    if body.watch is not None:
        if s["sensor_type"] != "phone":
            raise HTTPException(400, "Only camera sensors can watch for alerts")
        s = await sensor_store.set_watch(sensor_id, org, body.watch.model_dump(exclude_none=True))
    if "name" in fields and s["traccar_device_id"]:
        try:
            await traccar_client.rename_device(s["traccar_device_id"], s["name"], s["identifier"])
        except Exception as e:
            logger.warning(f"[sensors] Traccar rename failed: {e}")
    if body.enabled is False:
        await _kick(sensor_id)
    return await _public(s, admin=True)


@router.post("/{sensor_id}/pairing")
async def new_pairing(sensor_id: str, ctx: dict = Depends(require_org_admin)) -> Dict[str, Any]:
    _require_enabled()
    org = _org(ctx)
    s = await sensor_store.get_sensor(sensor_id, org)
    if not s or s["sensor_type"] != "phone":
        raise HTTPException(404, "Phone sensor not found")
    s = await sensor_store.update_sensor(sensor_id, org, pairing_token=sensor_store.new_pairing_token())
    await _kick(sensor_id)
    return await _public(s, admin=True)


@router.delete("/{sensor_id}", status_code=204)
async def delete_sensor(sensor_id: str, ctx: dict = Depends(require_org_admin)) -> None:
    _require_enabled()
    org = _org(ctx)
    s = await sensor_store.get_sensor(sensor_id, org)
    if not s:
        raise HTTPException(404, "Sensor not found")
    if s["traccar_device_id"]:
        try:
            await traccar_client.delete_device(s["traccar_device_id"])
        except Exception as e:
            logger.warning(f"[sensors] Traccar delete failed (removing here anyway): {e}")
    await sensor_store.delete_sensor(sensor_id, org)
    await _kick(sensor_id)
    logger.info(f"[sensors] {ctx['id']} deleted sensor {sensor_id}")


# ---------------------------------------------------------------- internal (hub -> backend)

def _check_hub(secret: Optional[str]) -> None:
    expected = settings.SENSOR_HUB_SECRET
    if not expected:
        raise HTTPException(503, "Sensors are not configured")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(401, "Invalid sensor hub secret")


class ResolveRequest(BaseModel):
    pairing_token: Optional[str] = None
    identifier: Optional[str] = None


class ReadingsRequest(BaseModel):
    events: List[Dict[str, Any]] = Field(default_factory=list, max_length=2000)


@router.post("/internal/resolve")
async def internal_resolve(body: ResolveRequest, x_sensor_hub_secret: Optional[str] = Header(None)) -> Dict[str, Any]:
    _check_hub(x_sensor_hub_secret)
    s = None
    if body.pairing_token:
        s = await sensor_store.find_by_token(body.pairing_token)
    elif body.identifier:
        s = await sensor_store.find_by_identifier(body.identifier)
    if not s:
        raise HTTPException(404, "Unknown sensor")
    return {"sensor_id": s["id"], "organization_id": s["organization_id"], "name": s["name"],
            "sensor_type": s["sensor_type"], "enabled": s["enabled"]}


@router.post("/internal/readings")
async def internal_readings(body: ReadingsRequest, x_sensor_hub_secret: Optional[str] = Header(None)) -> Dict[str, Any]:
    _check_hub(x_sensor_hub_secret)
    return {"stored": await sensor_store.apply_readings(body.events)}


@router.get("/internal/watches")
async def internal_watches(x_sensor_hub_secret: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Which cameras the hub should run the decision model on, and for what."""
    _check_hub(x_sensor_hub_secret)
    return {"watches": await sensor_store.active_watches(), "model": settings.DECISION_MODEL}


class AlertRequest(BaseModel):
    sensor_id: str
    rule_id: str
    label: str = Field(..., max_length=40)
    probability: float
    model: str = ""
    captured_ts: float  # ms
    jpeg_b64: Optional[str] = Field(None, max_length=4_000_000)


@router.post("/internal/alerts")
async def internal_alert(body: AlertRequest, x_sensor_hub_secret: Optional[str] = Header(None)) -> Dict[str, Any]:
    _check_hub(x_sensor_hub_secret)
    s = await sensor_store.get_sensor(body.sensor_id)
    if not s or not s["enabled"]:
        raise HTTPException(404, "Unknown sensor")
    a = await sensor_store.insert_alert(
        sensor=s, rule_id=body.rule_id, label=body.label, probability=body.probability, model=body.model,
        captured_at=datetime.fromtimestamp(body.captured_ts / 1000, tz=timezone.utc),
        jpeg=base64.b64decode(body.jpeg_b64) if body.jpeg_b64 else None)
    logger.info(f"[sensors] ALERT {a['id']}: {body.label} ({body.probability:.2f}) on {s['name']}")
    return {"alert_id": a["id"]}
