"""
Simulated phone sensor - for testing the hub without a real phone.

    uv run --with pillow --with websockets python fake_phone.py <pairing-token> [seconds]

The pairing token is the ?t=... part of the QR link SoldierIQ shows for a Phone sensor.

Connects to wss://127.0.0.1:8443/ws/sensor exactly like phone.html does and
sends camera frames (a drawn test image), GPS walking a small circle, compass
heading and motion readings.
"""

import asyncio
import io
import json
import math
import ssl
import struct
import sys
import time

import websockets
from PIL import Image, ImageDraw

URL = "wss://127.0.0.1:8443/ws/sensor"
LAT0, LON0 = 28.6139, 77.2090  # arbitrary test point


def frame(i: int) -> bytes:
    img = Image.new("RGB", (640, 360), (20, 30, 25))
    d = ImageDraw.Draw(img)
    x = int(320 + 250 * math.sin(i / 10))
    d.rectangle([x - 30, 150, x + 30, 210], fill=(76, 195, 138))
    d.text((12, 12), f"FAKE PHONE  frame {i}  {time.strftime('%H:%M:%S')}", fill=(230, 240, 232))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


async def main(token: str, duration: float) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # hub uses a self-signed cert
    async with websockets.connect(URL, ssl=ctx, max_size=None) as ws:
        await ws.send(json.dumps({"kind": "hello", "token": token}))
        print("hub:", await ws.recv())
        await ws.send(json.dumps({"kind": "status", "ts": int(time.time() * 1000),
                                  "data": {"battery": 87, "charging": False, "camera": "rear", "resolution": "640x360", "fps": 10}}))
        t0, i = time.time(), 0
        while time.time() - t0 < duration:
            ts = int(time.time() * 1000)
            a = i / 50
            await ws.send(struct.pack("<d", time.time() * 1000) + frame(i))  # capture time + JPEG, like phone.html
            await ws.send(json.dumps({"kind": "motion", "ts": ts, "data": {"accel": {"x": 0.1, "y": 0.0, "z": 9.8}, "rotation": {"alpha": 1, "beta": 0, "gamma": 0}}}))
            if i % 5 == 0:
                await ws.send(json.dumps({"kind": "position", "ts": ts, "data": {
                    "lat": LAT0 + 0.0003 * math.sin(a), "lon": LON0 + 0.0003 * math.cos(a),
                    "accuracy": 6, "altitude": 216, "heading": None, "speed": 1.4}}))
                await ws.send(json.dumps({"kind": "orientation", "ts": ts, "data": {
                    "heading": (math.degrees(a) + 90) % 360, "headingSource": "compass", "beta": 80, "gamma": 2}}))
            i += 1
            await asyncio.sleep(0.1)
    print(f"sent {i} frames")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 20))
