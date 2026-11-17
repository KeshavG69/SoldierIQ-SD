"""Live sensor tools for the chat agent.

The org's sensors (Connectors -> Sensors) are readable here:
  list_sensors        which sensors exist, live or not, where they are
  get_sensor_reading  newest position / heading / speed / battery of one sensor
  look_at_camera      hand the newest camera frame of a phone sensor to the chat model as an
                      image (agno ToolResult); the frame is also saved as a snapshot the reply shows
  sensor_history      where a sensor has been over the last N minutes
  show_sensors_map    sensors (+ trails) on the chat map card (same card as show_map)

Org and user come from the chat request context (utils/sandbox_context), so the
agent can only see its own organization's sensors. Readings come from the
SoldierIQ database (stored by the sensor hub); camera frames come straight from
the hub, which keeps the video.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from agno.media import Image
from agno.tools import tool
from agno.tools.function import ToolResult

from app.logger import logger
from app.settings import settings
from utils import sensor_store
from utils.sandbox_context import get_session_context

SNAPSHOT_TTL_S = 30 * 86400
FRAME_MAX_AGE_S = 15

SENSORS_INSTRUCTIONS = """<sensors>
You can read this organization's LIVE sensors (phones streaming camera + GPS + compass, and GPS trackers).
These are real-time devices, not documents: for questions about where a sensor/device/phone/tracker is,
what a camera sees, whether something is online, or where it has been, use the sensor tools, not the
knowledge base.

- list_sensors(): every sensor with live/offline status, last position and last-seen time. Call it first
  when you don't know the sensor's exact name.
- get_sensor_reading(sensor): newest reading for one sensor (position, accuracy, heading, speed, battery).
- look_at_camera(sensor): gives you the sensor's current camera frame as an image (next message). Look at
  it and answer the user's question concretely (people, vehicles, objects, text, anything unusual or
  security-relevant; say what can't be determined). It returns `snapshot_markdown`: put that line in your
  reply exactly as given so the user sees the frame you looked at. Only phone sensors have cameras.
- sensor_history(sensor, minutes): where the sensor has been (track summary).
- show_sensors_map(sensor=None, minutes=30): draws the sensors on an interactive map card under your reply
  (arrow = facing direction, line = recent trail; the user can tap a sensor and send it to TAK). Use it
  whenever the user asks where sensors are or wants a map. Never paste the map JSON.
- list_alerts(minutes=60, sensor=None): camera alerts the decision model raised (person, vehicle, bird, ...
  whatever each camera is set to watch for). Use for "any alerts?", "what happened at the gate?". Show the
  most relevant alert's `image_markdown` line exactly as given. Alerts are what the cameras are set up to
  watch for; if none are on, say how to turn them on.

Always say how fresh the data is (e.g. "as of 5 seconds ago"). If a sensor is offline, say when it was
last seen and give its last known data. Coordinates: give them with 5 decimals; the user can open them
on a map. Never invent readings.
</sensors>"""


# ---------------------------------------------------------------- helpers

def _org() -> Optional[str]:
    return get_session_context().get("org_id") or None


def _age_s(iso_or_dt) -> Optional[float]:
    if not iso_or_dt:
        return None
    dt = iso_or_dt if isinstance(iso_or_dt, datetime) else datetime.fromisoformat(str(iso_or_dt))
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def _ago(seconds: Optional[float]) -> str:
    if seconds is None:
        return "never"
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} hours ago"
    return f"{seconds / 86400:.1f} days ago"


def _status(s: dict) -> str:
    from routers.sensors import _status as status_of  # same rule as the Sensors tab

    return status_of(s)


def _summary(s: dict) -> Dict[str, Any]:
    latest = s.get("latest") or {}
    pos = (latest.get("position") or {}).get("data") or {}
    ori = (latest.get("orientation") or {}).get("data") or {}
    bat = (latest.get("status") or {}).get("data") or {}
    out: Dict[str, Any] = {
        "name": s["name"],
        "sensor_id": s["id"],
        "type": {"phone": "phone (camera + GPS + compass)", "gps_tracker": "GPS tracker"}.get(s["sensor_type"], s["sensor_type"]),
        "status": _status(s),
        "last_seen": _ago(_age_s(s["last_seen"])),
        "has_camera": s["sensor_type"] == "phone",
    }
    if pos.get("lat") is not None:
        p_age = (latest["position"].get("received_ts") or 0) / 1000
        out["position"] = {
            "lat": round(pos["lat"], 6), "lon": round(pos["lon"], 6),
            "accuracy_m": pos.get("accuracy_m"), "altitude_m": pos.get("alt_m"),
            "speed_kmh": round(pos["speed_mps"] * 3.6, 1) if pos.get("speed_mps") is not None else None,
            "course_deg": pos.get("course_deg"),
            "as_of": _ago(time.time() - p_age) if p_age else None,
            "map_link": f"https://www.openstreetmap.org/?mlat={pos['lat']:.6f}&mlon={pos['lon']:.6f}#map=17/{pos['lat']:.6f}/{pos['lon']:.6f}",
        }
    if ori.get("heading_deg") is not None:
        out["facing_deg"] = round(ori["heading_deg"])
        out["facing"] = _compass(ori["heading_deg"])
    if bat.get("battery_pct") is not None:
        out["battery_pct"] = bat["battery_pct"]
    return out


def _compass(deg: float) -> str:
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int(((deg % 360) + 22.5) // 45) % 8]


async def _find(sensor: str) -> tuple[Optional[dict], List[dict]]:
    """Match a sensor by id or (fuzzy) name inside the current org. Returns (match, all sensors)."""
    org = _org()
    if not org:
        return None, []
    rows = await sensor_store.list_sensors(org)
    q = (sensor or "").strip().lower()
    if not q:
        return (rows[0], rows) if len(rows) == 1 else (None, rows)
    for s in rows:
        if s["id"].lower() == q or s["name"].lower() == q:
            return s, rows
    partial = [s for s in rows if q in s["name"].lower() or s["name"].lower() in q]
    if len(partial) == 1:
        return partial[0], rows
    words = [w for w in q.replace("'", " ").split() if len(w) > 2]
    scored = sorted(((sum(w in s["name"].lower() for w in words), s) for s in rows), key=lambda x: -x[0])
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1], rows
    return None, rows


def _not_found(sensor: str, rows: List[dict]) -> str:
    if not _org():
        return json.dumps({"error": "No organization in this chat; sensors are unavailable."})
    if not rows:
        return json.dumps({"error": "This organization has no sensors yet. An admin can add one in Connectors -> Sensors."})
    return json.dumps({"error": f"No single sensor matches '{sensor}'.",
                       "available_sensors": [s["name"] for s in rows]})


def _snapshot_sig(snap_id: str) -> str:
    return hmac.new(settings.SENSOR_HUB_SECRET.encode(), f"snap.{snap_id}".encode(), hashlib.sha256).hexdigest()[:20]


def snapshot_url(snap_id: str) -> str:
    return f"{settings.PUBLIC_API_URL.rstrip('/')}/api/sensors/snapshots/{snap_id}.jpg?s={_snapshot_sig(snap_id)}"


def snapshot_sig_ok(snap_id: str, sig: str) -> bool:
    return bool(settings.SENSOR_HUB_SECRET) and hmac.compare_digest(_snapshot_sig(snap_id), sig or "")


async def save_snapshot(jpeg: bytes, meta: dict) -> str:
    from osint.core import cache_set

    snap_id = secrets.token_hex(12)
    await cache_set(f"sensor_snapshot:{snap_id}", {"jpeg_b64": base64.b64encode(jpeg).decode(), **meta}, SNAPSHOT_TTL_S)
    return snap_id


async def load_snapshot(snap_id: str) -> Optional[dict]:
    from osint.core import cache_get

    if not snap_id.isalnum() or len(snap_id) != 24:
        return None
    return await cache_get(f"sensor_snapshot:{snap_id}")


# ---------------------------------------------------------------- tools

@tool(stop_after_tool_call=False)
async def list_sensors() -> str:
    """List this organization's live sensors (phones and GPS trackers) with status (live/offline/waiting/paused),
    last-seen time, last known position and heading. Use it to answer "which sensors are online" or to find a
    sensor's exact name before calling the other sensor tools."""
    org = _org()
    if not org:
        return json.dumps({"error": "No organization in this chat; sensors are unavailable."})
    rows = await sensor_store.list_sensors(org)
    if not rows:
        return json.dumps({"sensors": [], "note": "No sensors yet. An admin can add one in Connectors -> Sensors."})
    sensors = [_summary(s) for s in rows]
    return json.dumps({"sensors": sensors, "live": sum(1 for s in sensors if s["status"] == "live"),
                       "total": len(sensors)})


@tool(stop_after_tool_call=False)
async def get_sensor_reading(sensor: str) -> str:
    """Newest reading of one sensor: position (lat/lon, accuracy, altitude), which way it faces (compass),
    speed, battery, and how fresh the data is.

    Args:
        sensor: The sensor's name (as shown in list_sensors) or id. Partial names work if unambiguous.
    """
    s, rows = await _find(sensor)
    if not s:
        return _not_found(sensor, rows)
    return json.dumps(_summary(s))


@tool(stop_after_tool_call=False)
async def look_at_camera(sensor: str) -> ToolResult:
    """Look through a phone sensor's camera RIGHT NOW: grabs the newest frame and gives it to you as an
    image (it arrives in the next message). Look at it yourself to answer the user's question. Also returns
    `snapshot_markdown`, an image line to include in your reply so the user sees the exact frame, plus where
    the camera is and which way it faces. Only phone sensors have cameras.

    Args:
        sensor: The sensor's name (as shown in list_sensors) or id.
    """
    s, rows = await _find(sensor)
    if not s:
        return ToolResult(content=_not_found(sensor, rows))
    if s["sensor_type"] != "phone":
        return ToolResult(content=json.dumps({"error": f"'{s['name']}' is a GPS tracker; it has no camera."}))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{settings.SENSOR_HUB_URL.rstrip('/')}/api/sensors/{s['id']}/frame.jpg",
                            headers={"X-Sensor-Hub-Secret": settings.SENSOR_HUB_SECRET})
    except httpx.HTTPError as e:
        logger.warning(f"[sensor_tools] hub unreachable: {e}")
        return ToolResult(content=json.dumps({"error": "The sensor hub is not reachable, so the camera can't be read right now."}))
    if r.status_code == 404:
        return ToolResult(content=json.dumps({
            "error": f"'{s['name']}' has not sent any camera frames. Is the sensor page open on the phone?",
            "status": _status(s), "last_seen": _ago(_age_s(s["last_seen"]))}))
    if r.status_code >= 400:
        return ToolResult(content=json.dumps({"error": f"Camera read failed (hub {r.status_code})."}))
    jpeg = r.content
    captured = int(r.headers.get("X-Captured-Ts") or 0) / 1000 or time.time()
    frame_age = max(0.0, time.time() - captured)

    snap_id = await save_snapshot(jpeg, {"sensor_id": s["id"], "org_id": s["organization_id"], "captured_at": captured})
    taken = datetime.fromtimestamp(captured, tz=timezone.utc).strftime("%H:%M:%S UTC")
    summary = _summary(s)
    out = {
        "sensor": s["name"],
        "frame": "attached as an image in the next message - look at it to answer",
        "frame_taken": _ago(frame_age) + f" ({taken})",
        "frame_is_live": frame_age <= FRAME_MAX_AGE_S,
        "snapshot_markdown": f"![{s['name']} camera, {taken}]({snapshot_url(snap_id)})",
    }
    if not out["frame_is_live"]:
        out["warning"] = "This frame is old; the camera may be offline. Say so."
    if summary.get("position"):
        out["camera_position"] = {k: summary["position"][k] for k in ("lat", "lon", "map_link")}
    if summary.get("facing"):
        out["camera_facing"] = f"{summary['facing']} ({summary['facing_deg']} deg)"
    return ToolResult(content=json.dumps(out), images=[Image(content=jpeg, format="jpeg")])


@tool(stop_after_tool_call=False)
async def sensor_history(sensor: str, minutes: int = 60) -> str:
    """Where a sensor has been: a summary of its recorded track over the last `minutes` (start and end position,
    distance covered, time span, and a few waypoints). Positions are recorded about every 5 seconds while live.

    Args:
        sensor: The sensor's name (as shown in list_sensors) or id.
        minutes: How far back to look, 1-1440 (default 60).
    """
    s, rows = await _find(sensor)
    if not s:
        return _not_found(sensor, rows)
    minutes = max(1, min(int(minutes or 60), 1440))
    pts = await sensor_store.recent_positions(s["id"], s["organization_id"], limit=2000)
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    pts = [p for p in pts if datetime.fromisoformat(p["ts"]) >= since][::-1]  # oldest first
    if not pts:
        return json.dumps({"sensor": s["name"], "minutes": minutes, "points": 0,
                           "note": f"No positions recorded in the last {minutes} minutes.",
                           "last_seen": _ago(_age_s(s["last_seen"]))})
    dist = sum(_haversine_m(a, b) for a, b in zip(pts, pts[1:]))
    step = max(1, len(pts) // 8)
    waypoints = [{"time": p["ts"][11:19] + " UTC", "lat": round(p["lat"], 6), "lon": round(p["lon"], 6)}
                 for p in pts[::step]][:10]
    first, last = pts[0], pts[-1]
    return json.dumps({
        "sensor": s["name"], "minutes": minutes, "points": len(pts),
        "from": {"time": first["ts"][11:19] + " UTC", "lat": round(first["lat"], 6), "lon": round(first["lon"], 6)},
        "to": {"time": last["ts"][11:19] + " UTC", "lat": round(last["lat"], 6), "lon": round(last["lon"], 6)},
        "distance_m": round(dist),
        "straight_line_m": round(_haversine_m(first, last)),
        "moved": dist > 30,
        "waypoints": waypoints,
    })


@tool(stop_after_tool_call=False)
async def show_sensors_map(sensor: Optional[str] = None, minutes: int = 30, title: Optional[str] = None) -> str:
    """Draw this organization's sensors on an interactive map under your reply: each sensor as an arrow
    pointing the way it faces (green = live, grey = offline) with its recent trail. The user can tap a sensor
    for details and send it to TAK. Use it whenever the user asks where sensors are or wants to see them on a
    map. After calling, describe the positions in a sentence or two; do not repeat every number.

    Args:
        sensor: Only this sensor (name or id). Omit to show all sensors.
        minutes: Trail length in minutes, 0-1440 (default 30). 0 = no trail.
        title: Optional map title.
    """
    from osint.visuals import store_map

    org = _org()
    if not org:
        return json.dumps({"type": "map", "error": "No organization in this chat; sensors are unavailable."})
    if sensor:
        s, rows = await _find(sensor)
        if not s:
            return _not_found(sensor, rows)
        chosen = [s]
    else:
        chosen = await sensor_store.list_sensors(org)
    minutes = max(0, min(int(minutes if minutes is not None else 30), 1440))

    features, trails, all_pts, missing = [], [], [], []
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    for s in chosen:
        info = _summary(s)
        pos = info.get("position")
        if not pos:
            missing.append(s["name"])
            continue
        status = info["status"]
        heading = info.get("facing_deg")
        if heading is None and pos.get("course_deg") is not None and (pos.get("speed_kmh") or 0) > 1:
            heading = pos["course_deg"]  # trackers: direction of travel
        latest_pos = (s.get("latest") or {}).get("position") or {}
        features.append({
            "id": f"sensor-{s['id']}", "layer": "sensors", "lat": pos["lat"], "lon": pos["lon"],
            "title": s["name"], "severity": "low" if status == "live" else "info",
            "time": datetime.fromtimestamp((latest_pos.get("received_ts") or 0) / 1000, tz=timezone.utc).isoformat()
            if latest_pos.get("received_ts") else None,
            "heading": heading, "source": f"SoldierIQ sensor ({info['type']})",
            "details": {k: v for k, v in {
                "Status": status, "Last seen": info["last_seen"], "Accuracy": f"±{round(pos['accuracy_m'])} m" if pos.get("accuracy_m") else None,
                "Facing": f"{info['facing']} ({info['facing_deg']}°)" if info.get("facing") else None,
                "Speed": f"{pos['speed_kmh']} km/h" if pos.get("speed_kmh") is not None else None,
                "Altitude": f"{round(pos['altitude_m'])} m" if pos.get("altitude_m") is not None else None,
                "Battery": f"{round(info['battery_pct'])}%" if info.get("battery_pct") is not None else None,
                "Camera": "yes" if info["has_camera"] else None,
            }.items() if v is not None},
        })
        all_pts.append((pos["lat"], pos["lon"]))
        if minutes:
            hist = await sensor_store.recent_positions(s["id"], s["organization_id"], limit=1500)
            coords = [[p["lon"], p["lat"]] for p in reversed(hist) if datetime.fromisoformat(p["ts"]) >= since]
            if len(coords) > 1:
                trails.append({"sensor_id": s["id"], "name": s["name"], "live": status == "live", "coords": coords})
                all_pts += [(c[1], c[0]) for c in coords]

    if not features:
        return json.dumps({"type": "map", "error": "No sensor has reported a position yet." if chosen else
                           "This organization has no sensors yet."})
    lats, lons = [p[0] for p in all_pts], [p[1] for p in all_pts]
    pad_lat = max(0.002, (max(lats) - min(lats)) * 0.15)
    pad_lon = max(0.002, (max(lons) - min(lons)) * 0.15)
    bbox = [min(lons) - pad_lon, min(lats) - pad_lat, max(lons) + pad_lon, max(lats) + pad_lat]
    notes = ["Arrows point where each phone camera faces (or a tracker's direction of travel).",
             "Positions are as accurate as the device's GPS (see Accuracy)."]
    if missing:
        notes.append("No position yet: " + ", ".join(missing))
    payload = {
        "type": "map", "title": title or ("Sensor: " + chosen[0]["name"] if sensor else "Sensors"),
        "region": "sensors", "bbox": bbox, "hours": round(minutes / 60, 2),
        "layers": [{"id": "sensors", "label": "Sensors", "icon": "sensor", "count": len(features)}],
        "features": features, "trails": trails, "notes": notes,
        "sources": [{"name": "SoldierIQ sensors", "ok": True, "fetched_at": datetime.now(timezone.utc).isoformat()}],
    }
    owner = f"{org}:{get_session_context().get('user_id')}"
    map_id = await store_map(payload, owner)
    return json.dumps({
        "type": "map", "map_id": map_id, "title": payload["title"], "region": "sensors", "bbox": bbox,
        "hours": payload["hours"], "icon_count": len(features), "layers": payload["layers"], "notes": notes,
        "sensors": [{"name": f["title"], "status": f["details"]["Status"], "lat": f["lat"], "lon": f["lon"],
                     "facing": f["details"].get("Facing")} for f in features],
        "trail_minutes": minutes, "trails_drawn": len(trails),
    })


@tool(stop_after_tool_call=False)
async def list_alerts(minutes: int = 60, sensor: Optional[str] = None) -> str:
    """Camera alerts raised by the decision model (e.g. a person, vehicle or bird seen on a camera), newest first.
    Each alert has what was seen, which camera, when, how sure the model was, where the camera was, whether
    someone marked it as seen, and `image_markdown` (the frame that triggered it) to show in your reply.

    Args:
        minutes: How far back to look, 1-10080 (default 60).
        sensor: Only alerts from this camera (name or id). Omit for all cameras.
    """
    from routers.sensors import alert_public

    org = _org()
    if not org:
        return json.dumps({"error": "No organization in this chat; sensors are unavailable."})
    sid = None
    if sensor:
        s, rows = await _find(sensor)
        if not s:
            return _not_found(sensor, rows)
        sid = s["id"]
    minutes = max(1, min(int(minutes or 60), 10080))
    rows = await sensor_store.list_alerts(org, since=datetime.now(timezone.utc) - timedelta(minutes=minutes),
                                          sensor_id=sid, limit=30)
    alerts = []
    for a in rows:
        p = alert_public(a)
        alerts.append({
            "what": p["label"], "camera": p["sensor_name"], "when": _ago(_age_s(p["created_at"])),
            "time_utc": p["created_at"][11:19], "confidence_pct": round(p["probability"] * 100),
            "seen_by_someone": p["acknowledged"],
            "position": {"lat": round(p["lat"], 6), "lon": round(p["lon"], 6)} if p["lat"] is not None else None,
            "image_markdown": f"![{p['label']} - {p['sensor_name']}]({p['image_url']})",
        })
    watching = [s["name"] for s in await sensor_store.list_sensors(org) if (s.get("watch") or {}).get("enabled")]
    return json.dumps({"minutes": minutes, "count": len(alerts), "alerts": alerts,
                       "cameras_watching": watching,
                       "note": None if watching else "No camera has alerts turned on (Connectors -> Sensors -> Camera alerts)."})


def _haversine_m(a: dict, b: dict) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


SENSOR_TOOLS = [list_sensors, get_sensor_reading, look_at_camera, sensor_history, show_sensors_map, list_alerts]
