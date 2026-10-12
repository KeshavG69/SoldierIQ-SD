# SoldierIQ voice agent

LiveKit Agents worker behind the mic button in the dashboard. It answers questions
about the user's selected documents by voice.

- **Pipeline:** Deepgram Nova-3 (STT) → GPT-6 Luna via OpenRouter (LLM, `VOICE_LLM_MODEL`)
  → Cartesia Sonic-2 (TTS), Silero VAD, LiveKit turn detector, BVC noise cancellation.
- **Search:** the `search_knowledge_base` tool calls the backend's `POST /api/voice/search`
  (`backend/routers/voice.py`), which runs the same knowledge-graph search as text chat.
- **Scope:** the Next.js route `frontend-nextjs/app/api/livekit/token` signs the user's
  organization and selected document ids into the LiveKit participant metadata.

## Avatar concierge ("Agent chat" button)

The same worker also runs a talking video avatar that helps people use the app. The token
route signs `mode: "concierge"` into the participant metadata; `agent.py` then starts
`ConciergeAgent` (`concierge.py`, no document search) behind a video avatar (`avatar.py`).
The avatar worker joins the room and publishes lip-synced video + audio for the agent; the
frontend renders it from `useVoiceAssistant().videoTrack`.

The provider is picked by which key is set, first match wins:

| Provider | Key | Face |
|---|---|---|
| Tavus | `TAVUS_API_KEY` | `TAVUS_FACE_ID`, default `rdd4c86e5e1a` "Steve - Professional"; stock faces: `GET tavusapi.com/v2/replicas?replica_type=system` |
| Simli | `SIMLI_API_KEY` | `SIMLI_FACE_ID`, default "Laila"; stock faces: docs.simli.com/api-reference/preset-faces |
| LemonSlice via LiveKit Inference | none (billed to LiveKit) | `AVATAR_IMAGE_URL`, any public face image. Not offered in every LiveKit region (refused in us-east as of Oct 2026) |

If the avatar can't start, the agent stops it and the concierge continues voice-only; the
frontend then shows the audio visualizer instead of video.

## Configuration

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | LLM |
| `BACKEND_URL` | Backend base URL, reachable from LiveKit Cloud (e.g. the Railway URL) |
| `VOICE_AGENT_SECRET` | Must equal the backend's `VOICE_AGENT_SECRET` |
| `VOICE_LLM_MODEL` | Optional, default `openai/gpt-6-luna` |
| `VOICE_DEV_METADATA` | Local console testing only: participant metadata JSON (add `"mode":"concierge"` for the avatar) |
| `TAVUS_API_KEY`, `TAVUS_FACE_ID`, `SIMLI_API_KEY`, `SIMLI_FACE_ID`, `AVATAR_IMAGE_URL` | Concierge avatar, see above |

## Tests

```bash
uv run pytest      # concierge behaviour tests need OPENROUTER_API_KEY (LLM-judged)
```

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
