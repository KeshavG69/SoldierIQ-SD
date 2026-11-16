"""
Traccar REST client - registers GPS tracker devices.

Traccar (open-source GPS server, runs next to the sensor hub) decodes 200+
tracker protocols. SoldierIQ only creates / renames / deletes devices here;
positions reach SoldierIQ through the sensor hub, already normalized.
"""

from __future__ import annotations

from typing import Optional

import httpx

from app.settings import settings


class TraccarError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    if not settings.TRACCAR_USER:
        raise TraccarError("Traccar is not configured (TRACCAR_USER / TRACCAR_PASSWORD)")
    return httpx.AsyncClient(
        base_url=settings.TRACCAR_URL.rstrip("/"),
        auth=(settings.TRACCAR_USER, settings.TRACCAR_PASSWORD),
        timeout=10,
    )


async def create_device(name: str, unique_id: str) -> int:
    try:
        async with _client() as c:
            r = await c.post("/api/devices", json={"name": name, "uniqueId": unique_id})
    except httpx.HTTPError as e:
        raise TraccarError(f"Traccar unreachable: {e}") from e
    if r.status_code >= 400:
        raise TraccarError(f"Traccar refused the device ({r.status_code}): {r.text[:200]}")
    return int(r.json()["id"])


async def rename_device(device_id: int, name: str, unique_id: str) -> None:
    async with _client() as c:
        r = await c.put(f"/api/devices/{device_id}", json={"id": device_id, "name": name, "uniqueId": unique_id})
    if r.status_code >= 400:
        raise TraccarError(f"Traccar rename failed ({r.status_code})")


async def delete_device(device_id: Optional[int]) -> None:
    if not device_id:
        return
    async with _client() as c:
        r = await c.delete(f"/api/devices/{device_id}")
    if r.status_code >= 400 and r.status_code != 404:
        raise TraccarError(f"Traccar delete failed ({r.status_code})")
