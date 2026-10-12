"""Voice-agent settings — loaded from .env locally, from LiveKit Cloud secrets in prod."""

from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(".env", override=True)


class Settings(BaseSettings):
    # LiveKit Cloud — auto-injected at runtime on LK Cloud deploys.
    LIVEKIT_URL: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""

    # LLM via OpenRouter
    OPENROUTER_API_KEY: str = ""
    VOICE_LLM_MODEL: str = "openai/gpt-6-luna"

    # Knowledge search: the SoldierIQ backend (same graph retrieval as text chat).
    # BACKEND_URL must be reachable from LiveKit Cloud (public URL, not localhost).
    # VOICE_AGENT_SECRET must equal the backend's VOICE_AGENT_SECRET.
    BACKEND_URL: str = ""
    VOICE_AGENT_SECRET: str = ""
    VOICE_SEARCH_TIMEOUT_S: float = 45.0

    # Avatar concierge (the dashboard's "Agent chat" button), see avatar.py.
    # Tavus: TAVUS_FACE_ID is a stock or custom face (replica) id. Default "Steve -
    # Professional" (suit and tie); also formal: rf1bd7e252de "Rose - Business",
    # rcd970fadf46 "Mary - Business". List: GET tavusapi.com/v2/replicas?replica_type=system
    TAVUS_API_KEY: str = ""
    TAVUS_FACE_ID: str = "rdd4c86e5e1a"
    # Simli: SIMLI_FACE_ID is any face from docs.simli.com/api-reference/preset-faces
    # (default "Laila") or one created at app.simli.com.
    SIMLI_API_KEY: str = ""
    SIMLI_FACE_ID: str = "b9e5fba3-071a-4e35-896e-211c4d6eaa7b"
    # LemonSlice via LiveKit Inference (used when SIMLI_API_KEY is empty): the face it
    # animates is any public image URL. Default is a free Unsplash photo
    # (unsplash.com/photos/SJvDxw0azqw), cropped to the 368x560 portrait.
    AVATAR_IMAGE_URL: str = (
        "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e"
        "?w=736&h=1120&fit=crop&crop=faces&fm=jpg&q=85"
    )

    # Local console testing only: participant metadata JSON to use when no
    # participant joins (e.g. {"organization_id": ..., "document_ids": [...]}).
    VOICE_DEV_METADATA: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
