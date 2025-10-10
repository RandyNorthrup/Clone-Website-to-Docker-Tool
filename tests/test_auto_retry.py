import pytest
from auto_retry import _risk_assess, FIELD_METADATA, ADJUSTABLE_FIELDS

def test_risk_assess_jobs_increase():
    current = {"jobs": 4}
    changes = {"jobs": 12}
    risks = _risk_assess(current, changes)
    assert "jobs" in risks
    assert "increase" in risks["jobs"]

def test_risk_assess_failure_threshold():
    current = {"failure_threshold": 0.1}
    changes = {"failure_threshold": 0.5}
    risks = _risk_assess(current, changes)
    assert "failure_threshold" in risks

def test_risk_assess_relaxed_tls():
    current = {"relaxed_tls": False}
    changes = {"relaxed_tls": True}
    risks = _risk_assess(current, changes)
    assert risks.get("relaxed_tls") == "relaxes TLS"

def test_risk_assess_checksums_disabled():
    current = {"checksums": True}
    changes = {"checksums": False}
    risks = _risk_assess(current, changes)
    assert risks.get("checksums") == "disables checksums"

def test_risk_assess_verify_after_disabled():
    current = {"verify_after": True}
    changes = {"verify_after": False}
    risks = _risk_assess(current, changes)
    assert risks.get("verify_after") == "disables verify_after"

def test_field_metadata_completeness():
    # All adjustable fields should have metadata
    for field in ADJUSTABLE_FIELDS:
        assert field in FIELD_METADATA
        assert "hint" in FIELD_METADATA[field]

# --- End of tests ---
