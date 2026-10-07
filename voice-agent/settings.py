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

    # Local console testing only: participant metadata JSON to use when no
    # participant joins (e.g. {"organization_id": ..., "document_ids": [...]}).
    VOICE_DEV_METADATA: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
