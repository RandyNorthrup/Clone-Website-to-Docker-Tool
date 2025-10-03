import pytest

from ai_chat import parse_ai_changes, assess_change_risks


def test_parse_ai_changes_simple():
    text = "Some analysis...\nChanges: {\"changes\": {\"prerender\": true, \"jobs\": 16, \"non_whitelist\": 123}}"
    changes = parse_ai_changes(text)
    assert changes == {"prerender": True, "jobs": 16}


def test_parse_ai_changes_missing():
    assert parse_ai_changes("No JSON here") is None


def test_parse_ai_changes_malformed_line_ignored():
    text = "Changes: {not valid json}"
    assert parse_ai_changes(text) is None


def test_assess_change_risks_jobs_increase():
    current = {"jobs": 6}
    proposed = {"jobs": 16}
    risks = assess_change_risks(current, proposed)
    assert "jobs" in risks and "16" in risks["jobs"]


def test_assess_change_risks_failure_threshold():
    current = {"failure_threshold": 0.1}
    proposed = {"failure_threshold": 0.35}
    risks = assess_change_risks(current, proposed)
    assert "failure_threshold" in risks


def test_assess_change_risks_relaxed_tls():
    current = {"relaxed_tls": False}
    proposed = {"relaxed_tls": True}
    risks = assess_change_risks(current, proposed)
    assert risks.get("relaxed_tls") == 'relaxes TLS verification'


def test_assess_change_risks_checksums_disabled():
    current = {"checksums": True}
    proposed = {"checksums": False}
    risks = assess_change_risks(current, proposed)
    assert risks.get("checksums") == 'disables checksums'


def test_assess_change_risks_verify_after_disabled():
    current = {"verify_after": True}
    proposed = {"verify_after": False}
    risks = assess_change_risks(current, proposed)
    assert risks.get("verify_after") == 'disables verification'
