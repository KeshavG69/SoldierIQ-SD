"""build_avatar() provider selection — constructs sessions only, no network calls."""

from unittest.mock import patch

import pytest
from livekit.agents import inference
from livekit.plugins import simli, tavus

import avatar
from settings import settings


@pytest.fixture(autouse=True)
def _livekit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")


def test_tavus_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TAVUS_API_KEY", "tavus-key")
    monkeypatch.setattr(settings, "TAVUS_FACE_ID", "r-face")
    monkeypatch.setattr(settings, "SIMLI_API_KEY", "simli-key")
    with patch.object(tavus.AvatarSession, "_ensure_http_session"):
        session = avatar.build_avatar()
    assert isinstance(session, tavus.AvatarSession)
    assert session._face_id == "r-face"


def test_simli_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TAVUS_API_KEY", "")
    monkeypatch.setattr(settings, "SIMLI_API_KEY", "simli-key")
    monkeypatch.setattr(settings, "SIMLI_FACE_ID", "face-123")
    # The plugin grabs the job's shared HTTP session on construction; there is no job here.
    with patch.object(simli.AvatarSession, "_ensure_http_session"):
        session = avatar.build_avatar()
    assert isinstance(session, simli.AvatarSession)
    assert session._simli_config.api_key == "simli-key"
    assert session._simli_config.face_id == "face-123"


def test_lemonslice_via_livekit_inference_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TAVUS_API_KEY", "")
    monkeypatch.setattr(settings, "SIMLI_API_KEY", "")
    monkeypatch.setattr(settings, "AVATAR_IMAGE_URL", "https://example.com/face.png")
    session = avatar.build_avatar()
    assert isinstance(session, inference.AvatarSession)
    assert session.provider == "lemonslice"
    assert session._extra_kwargs == {"image_url": "https://example.com/face.png"}
