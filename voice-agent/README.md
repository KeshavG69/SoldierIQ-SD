# SoldierIQ voice agent

LiveKit Agents worker behind the mic button in the dashboard. It answers questions
about the user's selected documents by voice.

- **Pipeline:** Deepgram Nova-3 (STT) → GPT-6 Luna via OpenRouter (LLM, `VOICE_LLM_MODEL`)
  → Cartesia Sonic-2 (TTS), Silero VAD, LiveKit turn detector, BVC noise cancellation.
- **Search:** the `search_knowledge_base` tool calls the backend's `POST /api/voice/search`
  (`backend/routers/voice.py`), which runs the same knowledge-graph search as text chat.
- **Scope:** the Next.js route `frontend-nextjs/app/api/livekit/token` signs the user's
  organization and selected document ids into the LiveKit participant metadata.

## Configuration

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | LLM |
| `BACKEND_URL` | Backend base URL, reachable from LiveKit Cloud (e.g. the Railway URL) |
| `VOICE_AGENT_SECRET` | Must equal the backend's `VOICE_AGENT_SECRET` |
| `VOICE_LLM_MODEL` | Optional, default `openai/gpt-6-luna` |
| `VOICE_DEV_METADATA` | Local console testing only: participant metadata JSON |

`LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` are injected automatically on
LiveKit Cloud; set them in `.env` for local runs.

## Run locally (your mic and speakers)

```bash
uv sync
uv run agent.py download-files
BACKEND_URL=http://localhost:8010 VOICE_AGENT_SECRET=... \
VOICE_DEV_METADATA='{"organization_id":"<org>","document_ids":["<doc>"]}' \
uv run agent.py console
```

## Deploy (LiveKit Cloud)

```bash
lk agent deploy        # from this directory; uses livekit.toml
lk agent logs          # tail the deployed worker
```
