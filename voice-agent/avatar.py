"""Video avatar for the concierge — a second participant that lip-syncs the agent's speech.

The avatar worker joins the room, receives the AgentSession's audio over a data stream
and publishes synchronized audio + video on behalf of the agent. Start it *before*
session.start() so the session's room audio output is skipped.

Provider, by which key is set: Tavus (TAVUS_API_KEY) → Simli (SIMLI_API_KEY) → LemonSlice
via LiveKit Inference (no extra key, but not offered in every LiveKit region).
"""

from __future__ import annotations

from livekit.agents import inference
from livekit.agents.voice.avatar import AvatarSession
from livekit.plugins import simli, tavus

from settings import settings

AVATAR_NAME = "SoldierIQ Concierge"


def build_avatar() -> AvatarSession:
    if settings.TAVUS_API_KEY:
        # No pal → the plugin uses Tavus's stock "echo" pal, which only renders our audio.
        return tavus.AvatarSession(
            api_key=settings.TAVUS_API_KEY,
            face_id=settings.TAVUS_FACE_ID or None,
            avatar_participant_name=AVATAR_NAME,
        )

    if settings.SIMLI_API_KEY:
        return simli.AvatarSession(
            simli_config=simli.SimliConfig(api_key=settings.SIMLI_API_KEY, face_id=settings.SIMLI_FACE_ID),
            avatar_participant_name=AVATAR_NAME,
        )

    # LemonSlice animates a still image: a public URL returning image/*, face and mouth
    # clearly visible; rendered at 368x560 (portrait), center-cropped if needed.
    return inference.AvatarSession(
        "lemonslice",
        extra_kwargs=inference.LemonSliceOptions(image_url=settings.AVATAR_IMAGE_URL),
        avatar_participant_name=AVATAR_NAME,
    )
