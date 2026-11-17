# SoldierIQ Sensor Hub

Receives live sensor data, converts it to one common format, and forwards it to
SoldierIQ. Sensors are added by org admins in SoldierIQ → Connectors → Sensors.

```
Phone (browser page, QR pairing) ──► hub :8443 ─┐
GPS tracker / Traccar Client app ──► Traccar ───┼─► normalized readings ──► SoldierIQ backend
                                    (hub polls) ┘     (camera video stays on the hub;
                                                       browsers get a signed URL)
```

## Run it locally

1. **Traccar** (GPS server, needs Docker / OrbStack):

   ```bash
   docker compose -f sensor-hub/traccar/docker-compose.yml up -d
   ```

   The first time, create its admin user (registration is open only while there are no users):

   ```bash
   curl -X POST http://127.0.0.1:8082/api/users -H 'Content-Type: application/json' \
     -d '{"name":"soldieriq","email":"soldieriq@local","password":"<pick one>"}'
   ```

2. **Hub config**: `sensor-hub/.env`

   ```
   SENSOR_HUB_SECRET=<long random string, same as the backend>
   SOLDIERIQ_API_URL=http://127.0.0.1:8010
   TRACCAR_URL=http://127.0.0.1:8082
   TRACCAR_USER=soldieriq@local
   TRACCAR_PASSWORD=<the password above>
   OPENROUTER_API_KEY=<key>   # camera alerts (decision model); optional
   ```

3. **Backend config**: add the same values to `backend/.env`:
   `SENSOR_HUB_SECRET`, `TRACCAR_URL`, `TRACCAR_USER`, `TRACCAR_PASSWORD`
   (optional: `SENSOR_HUB_URL`, `SENSOR_HUB_VIEW_URL`, `TRACCAR_OSMAND_PORT`).

4. Start the hub: `uv --directory sensor-hub run python server.py` (or the `sensor-hub`
   entry in `.claude/launch.json`), then the backend and frontend as usual.

## Camera alerts (decision model)

In SoldierIQ → Connectors → Sensors, open a phone sensor → **Camera alerts**: switch on and choose what
to alert on (Person, Vehicle, Bird, or anything typed). Every few seconds the hub sends the newest frame to
Perplexity Decider v1.2 (OpenRouter decisions API, `DECISION_MODEL` in the backend) with one yes/no
question per item. An item alerts when it is above its threshold in 2 of the last 3 checks, then stays
quiet for 60 s (`ALERT_COOLDOWN_S`). Alerts (with the frame) appear as pop-ups in SoldierIQ, in the
Sensors tab, and to the chat assistant (`list_alerts`).

## Cost control: motion check

Before each model call the hub compares the frame with the last one the model saw (32x24 grayscale
thumbnail, ~1.4 ms, no AI). If nothing changed it skips the call; after a change it keeps checking for 12 s,
and a heartbeat check still runs once a minute. Per camera in SoldierIQ: **Check every** 2-30 s and
**Only check when something moves** (on by default). Env knobs: `MOTION_THRESHOLD` (6),
`MOTION_HOLD_S` (12), `HEARTBEAT_S` (60).

## Deploy on Railway

The hub switches to **cloud mode** when `PORT` is set: one plain-HTTP listener (Railway terminates HTTPS,
so phones get no certificate warning) and everything except the phone page, `/health` and signed video
links needs the `X-Sensor-Hub-Secret` header.

1. New service from this repo, **Root Directory** `sensor-hub` (uses `Dockerfile` + `railway.json`:
   1 replica, health check `/health`). Generate a public domain.
2. Hub variables:
   ```
   SENSOR_HUB_SECRET=<same as backend>
   PUBLIC_URL=https://<hub-domain>             # phone pairing links
   SOLDIERIQ_API_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:${{backend.PORT}}
   OPENROUTER_API_KEY=<key>                    # camera alerts
   # GPS trackers only: TRACCAR_URL / TRACCAR_USER / TRACCAR_PASSWORD, TRACKER_HOST=<traccar public host>
   ```
3. Backend variables:
   ```
   SENSOR_HUB_URL=http://${{sensor-hub.RAILWAY_PRIVATE_DOMAIN}}:${{sensor-hub.PORT}}
   SENSOR_HUB_VIEW_URL=https://<hub-domain>    # browsers load live video from here
   SENSOR_HUB_SECRET=<same>
   PUBLIC_API_URL=https://<backend-domain>     # signed snapshot / alert image links in chat
   ```
4. Keep it at **one replica**: live frames and phone connections are held in memory. To grow, run more
   hubs and split organizations between them.
5. **Traccar** (only for GPS trackers), a third service:
   - New service from this repo, **Root Directory** `sensor-hub/traccar` (Dockerfile pins `traccar/traccar:6.17.0`).
   - **Volume** mounted at `/opt/traccar/data` (its database). Without it every redeploy starts empty.
   - Variable `PORT=5055`, then **generate a domain**: the Traccar Client app sends to it over HTTPS.
     Do not expose 8082 (Traccar's admin API / web UI); SoldierIQ reaches it over the private network.
   - Hardware trackers (raw TCP): add a **TCP proxy** for the protocol's port (Teltonika 5027, GT06 5023)
     and put the proxy's `host:port` in the backend's `TRACCAR_TCP_ENDPOINT`.
   - No manual admin setup: on a fresh Traccar, SoldierIQ creates the admin user from
     `TRACCAR_USER` / `TRACCAR_PASSWORD` the first time a tracker is added.
   - Backend variables:
     ```
     TRACCAR_URL=http://${{traccar.RAILWAY_PRIVATE_DOMAIN}}:8082
     TRACCAR_USER=<an email-like login, e.g. soldieriq@local>
     TRACCAR_PASSWORD=<long random password>
     TRACCAR_PUBLIC_URL=https://<traccar-domain>
     TRACCAR_TCP_ENDPOINT=<proxy-host:port>     # only for hardware trackers
     ```
   - Hub variables: the same `TRACCAR_URL` / `TRACCAR_USER` / `TRACCAR_PASSWORD`.

## Ports

| Port | What | Who connects |
|---|---|---|
| 8443 (HTTPS, LAN) | phone page, phone WebSocket, signed video URLs | phones |
| 8090 (HTTP, localhost only) | full hub API, debug viewer at `/` | SoldierIQ backend, browsers on this machine |
| 5055 / 5027 / 5023 | Traccar: OsmAnd (Traccar Client app) / Teltonika / GT06 | GPS trackers |
| 8082 (localhost only) | Traccar REST API | backend, hub |

## Testing without a phone

```bash
uv --directory sensor-hub run --with pillow --with websockets python fake_phone.py <pairing-token> 60
curl "http://<lan-ip>:5055/?id=<tracker-device-id>&lat=28.6&lon=77.2&speed=10&timestamp=$(date +%s)"
```
