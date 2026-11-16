"""
Sensor registry (PostgreSQL).

A sensor belongs to one organization and has a type:
  phone        - phone browser streaming camera + GPS + compass via the sensor hub,
                 paired by a secret token inside a QR code
  gps_tracker  - any GPS tracker (or the Traccar Client phone app) reporting to
                 Traccar, identified by its device ID / IMEI

`latest` holds the newest normalized reading per kind (position, orientation,
status, connection); `sensor_positions` keeps position history: one point per
5 s per sensor, deleted after SENSOR_HISTORY_DAYS (default 30).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.logger import logger
from clients.postgres_client import get_postgres_client

SENSOR_TYPES = ("phone", "gps_tracker")
HISTORY_EVERY_S = 5.0
_last_history: Dict[str, float] = {}
PRUNE_EVERY_S = 3600  # how often old history is deleted (checked when readings arrive)
_last_prune = 0.0

_DDL = """
CREATE TABLE IF NOT EXISTS public.sensors (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    identifier TEXT,
    pairing_token TEXT,
    traccar_device_id INTEGER,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen TIMESTAMPTZ,
    latest JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sensors_org ON public.sensors (organization_id);
CREATE UNIQUE INDEX IF NOT EXISTS sensors_identifier_key ON public.sensors (identifier) WHERE identifier IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS sensors_pairing_token_key ON public.sensors (pairing_token) WHERE pairing_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.sensor_positions (
    id BIGSERIAL PRIMARY KEY,
    sensor_id TEXT NOT NULL REFERENCES public.sensors(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_sensor_positions_sensor_ts ON public.sensor_positions (sensor_id, ts DESC);

-- Camera watch (decision model): {"enabled": bool, "interval_s": n, "rules": [{"id","label","question","threshold"}]}
ALTER TABLE public.sensors ADD COLUMN IF NOT EXISTS watch JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS public.sensor_alerts (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    sensor_id TEXT NOT NULL REFERENCES public.sensors(id) ON DELETE CASCADE,
    rule_id TEXT,
    label TEXT NOT NULL,
    probability DOUBLE PRECISION,
    model TEXT,
    captured_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    heading DOUBLE PRECISION,
    snapshot BYTEA,
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sensor_alerts_org_time ON public.sensor_alerts (organization_id, created_at DESC);
"""
_TABLE_READY = False

_COLUMNS = ("id, organization_id, name, sensor_type, identifier, pairing_token, traccar_device_id, "
            "enabled, last_seen, latest, watch, created_by, created_at, updated_at")


_DDL_LOCK = asyncio.Lock()
_DDL_ADVISORY_KEY = 7_405_311  # serialises the DDL across processes (several workers / reloads)


async def _pool():
    global _TABLE_READY
    pool = await get_postgres_client().get_pool()
    if not _TABLE_READY:
        async with _DDL_LOCK:  # one request in this process runs the DDL; the rest wait for it
            if not _TABLE_READY:
                async with pool.acquire() as conn, conn.transaction():
                    await conn.execute("SELECT pg_advisory_xact_lock($1)", _DDL_ADVISORY_KEY)
                    await conn.execute(_DDL)
                _TABLE_READY = True
    return pool


def _row(r) -> Dict[str, Any]:
    d = dict(r)
    for k in ("latest", "watch"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    return d


def new_sensor_id() -> str:
    return "sen_" + secrets.token_hex(6)


def new_pairing_token() -> str:
    return secrets.token_urlsafe(24)


def new_tracker_identifier() -> str:
    """Short numeric ID that is easy to type into the Traccar Client app."""
    return "siq" + "".join(secrets.choice("0123456789") for _ in range(7))


async def create_sensor(*, organization_id: str, name: str, sensor_type: str, created_by: str,
                        identifier: Optional[str] = None, pairing_token: Optional[str] = None,
                        traccar_device_id: Optional[int] = None, sensor_id: Optional[str] = None) -> Dict[str, Any]:
    pool = await _pool()
    row = await pool.fetchrow(
        f"""INSERT INTO public.sensors (id, organization_id, name, sensor_type, identifier, pairing_token,
                                        traccar_device_id, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING {_COLUMNS}""",
        sensor_id or new_sensor_id(), organization_id, name, sensor_type, identifier, pairing_token,
        traccar_device_id, created_by,
    )
    return _row(row)


async def identifier_taken(identifier: str) -> bool:
    pool = await _pool()
    return bool(await pool.fetchval("SELECT 1 FROM public.sensors WHERE identifier = $1", identifier))


async def list_sensors(organization_id: str) -> List[Dict[str, Any]]:
    pool = await _pool()
    rows = await pool.fetch(
        f"SELECT {_COLUMNS} FROM public.sensors WHERE organization_id = $1 ORDER BY created_at", organization_id)
    return [_row(r) for r in rows]


async def get_sensor(sensor_id: str, organization_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    pool = await _pool()
    if organization_id is None:
        row = await pool.fetchrow(f"SELECT {_COLUMNS} FROM public.sensors WHERE id = $1", sensor_id)
    else:
        row = await pool.fetchrow(
            f"SELECT {_COLUMNS} FROM public.sensors WHERE id = $1 AND organization_id = $2", sensor_id, organization_id)
    return _row(row) if row else None


async def find_by_token(token: str) -> Optional[Dict[str, Any]]:
    pool = await _pool()
    row = await pool.fetchrow(f"SELECT {_COLUMNS} FROM public.sensors WHERE pairing_token = $1", token)
    return _row(row) if row else None


async def find_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    pool = await _pool()
    row = await pool.fetchrow(f"SELECT {_COLUMNS} FROM public.sensors WHERE identifier = $1", identifier)
    return _row(row) if row else None


async def update_sensor(sensor_id: str, organization_id: str, **fields) -> Optional[Dict[str, Any]]:
    allowed = {k: v for k, v in fields.items() if k in ("name", "enabled", "pairing_token")}
    if not allowed:
        return await get_sensor(sensor_id, organization_id)
    sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(allowed))
    pool = await _pool()
    row = await pool.fetchrow(
        f"UPDATE public.sensors SET {sets}, updated_at = now() WHERE id = $1 AND organization_id = $2 RETURNING {_COLUMNS}",
        sensor_id, organization_id, *allowed.values(),
    )
    return _row(row) if row else None


async def delete_sensor(sensor_id: str, organization_id: str) -> bool:
    pool = await _pool()
    res = await pool.execute("DELETE FROM public.sensors WHERE id = $1 AND organization_id = $2", sensor_id, organization_id)
    return res.endswith("1")


def _ts(ms: Any) -> datetime:
    try:
        return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return datetime.now(timezone.utc)


async def apply_readings(events: List[Dict[str, Any]]) -> int:
    """Store normalized readings pushed by the sensor hub. Unknown or paused sensors are ignored."""
    by_sensor: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        if isinstance(e, dict) and e.get("sensor_id") and e.get("kind"):
            by_sensor.setdefault(str(e["sensor_id"]), []).append(e)
    if not by_sensor:
        return 0
    pool = await _pool()
    stored = 0
    position_rows: List[tuple] = []
    sensor_updates: List[tuple] = []
    # Few round trips per batch: the database may be remote (each trip ~0.5 s).
    async with pool.acquire() as conn:
        known = await conn.fetch(
            "SELECT id, organization_id, enabled FROM public.sensors WHERE id = ANY($1::text[])", list(by_sensor))
        for k in known:
            if not k["enabled"]:
                continue
            evs = sorted(by_sensor[k["id"]], key=lambda e: e.get("received_ts") or 0)
            latest: Dict[str, Any] = {}
            for e in evs:
                kind = e["kind"]
                latest["connection" if kind in ("connected", "disconnected") else kind] = e
                if kind == "position":
                    d = e.get("data") or {}
                    # history: at most one point per HISTORY_EVERY_S per sensor (phones report ~1/s)
                    ts_s = float(e.get("received_ts") or 0) / 1000  # hub clock: immune to bad device clocks
                    if ts_s - _last_history.get(k["id"], 0) < HISTORY_EVERY_S:
                        continue
                    _last_history[k["id"]] = ts_s
                    if d.get("lat") is not None and d.get("lon") is not None:
                        position_rows.append((k["id"], k["organization_id"], _ts(e.get("ts")), float(d["lat"]),
                                              float(d["lon"]), json.dumps(d)))
            last = max((e.get("received_ts") or 0) for e in evs)
            sensor_updates.append((k["id"], json.dumps(latest), _ts(last)))
            stored += len(evs)
        async with conn.transaction():
            if position_rows:
                await conn.executemany(
                    """INSERT INTO public.sensor_positions (sensor_id, organization_id, ts, lat, lon, data)
                       VALUES ($1, $2, $3, $4, $5, $6::jsonb)""", position_rows)
            if sensor_updates:
                await conn.executemany(
                    """UPDATE public.sensors SET latest = latest || $2::jsonb,
                              last_seen = GREATEST(COALESCE(last_seen, 'epoch'::timestamptz), $3)
                       WHERE id = $1""", sensor_updates)
    await _maybe_prune(pool)
    return stored


async def _maybe_prune(pool) -> None:
    """Delete position history older than SENSOR_HISTORY_DAYS (at most once an hour)."""
    global _last_prune
    from app.settings import settings

    if time.time() - _last_prune < PRUNE_EVERY_S or settings.SENSOR_HISTORY_DAYS <= 0:
        return
    _last_prune = time.time()
    try:
        res = await pool.execute(
            "DELETE FROM public.sensor_positions WHERE ts < now() - make_interval(days => $1)",
            int(settings.SENSOR_HISTORY_DAYS))
        await pool.execute(
            "DELETE FROM public.sensor_alerts WHERE created_at < now() - make_interval(days => $1)",
            int(settings.SENSOR_HISTORY_DAYS))
        logger.info(f"[sensors] pruned history older than {settings.SENSOR_HISTORY_DAYS} days: {res}")
    except Exception as e:  # noqa: BLE001 - pruning must never break ingest
        logger.warning(f"[sensors] history prune failed: {e}")


async def recent_positions(sensor_id: str, organization_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    pool = await _pool()
    rows = await pool.fetch(
        """SELECT ts, lat, lon, data FROM public.sensor_positions
           WHERE sensor_id = $1 AND organization_id = $2 ORDER BY ts DESC LIMIT $3""",
        sensor_id, organization_id, limit,
    )
    return [{"ts": r["ts"].isoformat(), "lat": r["lat"], "lon": r["lon"],
             "data": json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]} for r in rows]


# ---------------------------------------------------------------- camera watch + alerts

DEFAULT_RULES = [
    {"id": "person", "label": "Person", "question": "Is at least one person visible?"},
    {"id": "vehicle", "label": "Vehicle", "question": "Is a car, truck, motorcycle or other vehicle visible?"},
    {"id": "weapon", "label": "Weapon", "question": "Is a gun, knife or other weapon visible?"},
    {"id": "drone", "label": "Drone / aircraft", "question": "Is a drone or small aircraft visible?"},
    {"id": "fire", "label": "Fire / smoke", "question": "Is fire or smoke visible?"},
]
DEFAULT_THRESHOLD = 0.85
DEFAULT_INTERVAL_S = 3.0


def normalize_watch(w: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    w = dict(w or {})
    rules = w.get("rules")
    if rules is None:
        rules = DEFAULT_RULES
    clean, seen = [], set()
    for r in rules[:12]:
        label = str(r.get("label") or "").strip()[:40]
        if not label:
            continue
        rid = str(r.get("id") or "".join(c if c.isalnum() else "_" for c in label.lower())).strip("_")[:40] or "rule"
        while rid in seen:
            rid += "_"
        seen.add(rid)
        clean.append({
            "id": rid, "label": label,
            "question": (str(r.get("question") or "").strip() or f"Is there any {label.lower()} visible in the image?")[:200],
            "threshold": min(0.99, max(0.5, float(r.get("threshold") or DEFAULT_THRESHOLD))),
        })
    return {"enabled": bool(w.get("enabled")),
            "interval_s": min(30.0, max(1.0, float(w.get("interval_s") or DEFAULT_INTERVAL_S))),
            "rules": clean}


async def set_watch(sensor_id: str, organization_id: str, watch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pool = await _pool()
    row = await pool.fetchrow(
        f"UPDATE public.sensors SET watch = $3::jsonb, updated_at = now() WHERE id = $1 AND organization_id = $2 RETURNING {_COLUMNS}",
        sensor_id, organization_id, json.dumps(normalize_watch(watch)))
    return _row(row) if row else None


async def active_watches() -> Dict[str, Dict[str, Any]]:
    """sensor_id -> watch config, for every enabled sensor with watch on (all orgs; the hub asks)."""
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT id, watch FROM public.sensors WHERE enabled AND sensor_type = 'phone' AND (watch->>'enabled')::boolean IS TRUE")
    return {r["id"]: normalize_watch(json.loads(r["watch"]) if isinstance(r["watch"], str) else r["watch"]) for r in rows}


_ALERT_COLS = ("a.id, a.organization_id, a.sensor_id, s.name AS sensor_name, a.rule_id, a.label, a.probability, a.model, "
               "a.captured_at, a.created_at, a.lat, a.lon, a.heading, a.acknowledged_by, a.acknowledged_at")


async def insert_alert(*, sensor: Dict[str, Any], rule_id: str, label: str, probability: float, model: str,
                       captured_at: datetime, jpeg: Optional[bytes]) -> Dict[str, Any]:
    latest = sensor.get("latest") or {}
    pos = (latest.get("position") or {}).get("data") or {}
    ori = (latest.get("orientation") or {}).get("data") or {}
    pool = await _pool()
    alert_id = "alr_" + secrets.token_hex(8)
    await pool.execute(
        """INSERT INTO public.sensor_alerts (id, organization_id, sensor_id, rule_id, label, probability, model,
                                            captured_at, lat, lon, heading, snapshot)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
        alert_id, sensor["organization_id"], sensor["id"], rule_id, label, probability, model, captured_at,
        pos.get("lat"), pos.get("lon"), ori.get("heading_deg"), jpeg)
    return await get_alert(alert_id, sensor["organization_id"])


async def get_alert(alert_id: str, organization_id: str) -> Optional[Dict[str, Any]]:
    pool = await _pool()
    row = await pool.fetchrow(
        f"SELECT {_ALERT_COLS} FROM public.sensor_alerts a JOIN public.sensors s ON s.id = a.sensor_id "
        "WHERE a.id = $1 AND a.organization_id = $2", alert_id, organization_id)
    return dict(row) if row else None


async def list_alerts(organization_id: str, *, since: Optional[datetime] = None, sensor_id: Optional[str] = None,
                      limit: int = 50) -> List[Dict[str, Any]]:
    pool = await _pool()
    rows = await pool.fetch(
        f"""SELECT {_ALERT_COLS} FROM public.sensor_alerts a JOIN public.sensors s ON s.id = a.sensor_id
            WHERE a.organization_id = $1 AND ($2::timestamptz IS NULL OR a.created_at > $2)
              AND ($3::text IS NULL OR a.sensor_id = $3)
            ORDER BY a.created_at DESC LIMIT $4""",
        organization_id, since, sensor_id, max(1, min(limit, 200)))
    return [dict(r) for r in rows]


async def alert_snapshot(alert_id: str) -> Optional[bytes]:
    pool = await _pool()
    return await pool.fetchval("SELECT snapshot FROM public.sensor_alerts WHERE id = $1", alert_id)


async def acknowledge_alert(alert_id: str, organization_id: str, user_id: str) -> bool:
    pool = await _pool()
    res = await pool.execute(
        "UPDATE public.sensor_alerts SET acknowledged_by = $3, acknowledged_at = now() "
        "WHERE id = $1 AND organization_id = $2 AND acknowledged_at IS NULL", alert_id, organization_id, user_id)
    return res.endswith("1")
