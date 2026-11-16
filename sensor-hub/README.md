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
