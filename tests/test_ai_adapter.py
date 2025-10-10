import pytest
import os
import json
from fastapi.testclient import TestClient
from ai_adapter import app, ADJUSTABLE_SANITY, SENSITIVE_KEYS

client = TestClient(app)


def test_post_empty_payload_returns_empty_changes():
    payload = {
        "attempt": 1,
        "max_attempts": 3,
        "base_config": {},
        "current_config": {},
        "recent_logs": [],
        "adjustable_fields": ["jobs", "prerender"]
    }
    response = client.post("/cw2dt-ai", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "changes" in data
    assert isinstance(data["changes"], dict)




def test_adjustable_sanity_ranges():
    # All adjustable sanity fields should have valid ranges
    for field, rng in ADJUSTABLE_SANITY.items():
        assert isinstance(rng, tuple)
        assert len(rng) == 2
        assert rng[0] < rng[1]

# --- End of tests ---
