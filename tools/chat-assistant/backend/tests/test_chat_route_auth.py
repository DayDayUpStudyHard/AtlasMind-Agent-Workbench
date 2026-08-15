import pytest
from fastapi import HTTPException

from app.api.routes import _check_internal_token
from app.config import settings


def test_chat_internal_token_rejects_missing_or_invalid_value(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-internal-token")

    with pytest.raises(HTTPException) as missing:
        _check_internal_token(None)
    assert missing.value.status_code == 403

    with pytest.raises(HTTPException) as invalid:
        _check_internal_token("wrong-token")
    assert invalid.value.status_code == 403


def test_chat_internal_token_accepts_matching_value(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-internal-token")

    _check_internal_token("test-internal-token")
