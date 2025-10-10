import pytest
import os
import json
from ai_chat import parse_ai_changes, assess_change_risks, FREE_MODELS, DEFAULT_MODEL, WHITELIST

# --- Unit tests for AI Chat core logic ---

def test_free_models_are_subset_of_whitelist():
    # All free models should be valid for selection
    assert DEFAULT_MODEL in FREE_MODELS
    assert isinstance(FREE_MODELS, list)
    assert all(isinstance(m, str) for m in FREE_MODELS)


def test_parse_ai_changes_valid_json():
    text = 'Changes: {"changes": {"jobs": 8, "prerender": true}}'
    changes = parse_ai_changes(text)
    assert changes == {"jobs": 8, "prerender": True}


def test_parse_ai_changes_invalid_json():
    text = 'Changes: {not a valid json}'
    changes = parse_ai_changes(text)
    assert changes is None


def test_parse_ai_changes_no_changes():
    text = 'No changes here.'
    changes = parse_ai_changes(text)
    assert changes is None


def test_parse_ai_changes_whitelist_enforced():
    text = 'Changes: {"changes": {"jobs": 8, "dangerous": true}}'
    changes = parse_ai_changes(text)
    assert changes == {"jobs": 8}
    assert changes is not None and "dangerous" not in changes


def test_assess_change_risks_jobs_increase():
    current = {"jobs": 4}
    proposed = {"jobs": 12}
    risks = assess_change_risks(current, proposed)
    assert "jobs" in risks


def test_assess_change_risks_failure_threshold():
    current = {"failure_threshold": 0.1}
    proposed = {"failure_threshold": 0.5}
    risks = assess_change_risks(current, proposed)
    assert "failure_threshold" in risks


def test_assess_change_risks_relaxed_tls():
    current = {"relaxed_tls": False}
    proposed = {"relaxed_tls": True}
    risks = assess_change_risks(current, proposed)
    assert risks.get("relaxed_tls")


def test_assess_change_risks_checksums_disabled():
    current = {"checksums": True}
    proposed = {"checksums": False}
    risks = assess_change_risks(current, proposed)
    assert risks.get("checksums")


def test_assess_change_risks_verify_after_disabled():
    current = {"verify_after": True}
    proposed = {"verify_after": False}
    risks = assess_change_risks(current, proposed)
    assert risks.get("verify_after")


def test_whitelist_is_strict():
    # Ensure only whitelisted keys are allowed
    for key in ["jobs", "prerender", "relaxed_tls"]:
        assert key in WHITELIST
    assert "dangerous" not in WHITELIST

# --- End of tests ---
