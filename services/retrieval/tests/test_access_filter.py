from __future__ import annotations

from common.models import ConfidentialityTier

from app.filters import apply_access_filter
from tests.conftest import _make_chunk


def test_filters_out_wrong_tenant():
    chunks = [_make_chunk("c1", "text", tenant_id="t1"), _make_chunk("c2", "text", tenant_id="t2")]
    allowed, dropped = apply_access_filter(chunks, "t1", "matter-1", [ConfidentialityTier.STANDARD])
    assert [c.chunk_id for c in allowed] == ["c1"]
    assert dropped == 1


def test_filters_out_wrong_matter():
    chunks = [
        _make_chunk("c1", "text", matter_or_patient_id="matter-1"),
        _make_chunk("c2", "text", matter_or_patient_id="matter-2"),
    ]
    allowed, dropped = apply_access_filter(chunks, "t1", "matter-1", [ConfidentialityTier.STANDARD])
    assert [c.chunk_id for c in allowed] == ["c1"]
    assert dropped == 1


def test_filters_out_disallowed_confidentiality_tier():
    chunks = [
        _make_chunk("c1", "text", tier=ConfidentialityTier.STANDARD),
        _make_chunk("c2", "text", tier=ConfidentialityTier.PHI),
    ]
    allowed, dropped = apply_access_filter(chunks, "t1", "matter-1", [ConfidentialityTier.STANDARD])
    assert [c.chunk_id for c in allowed] == ["c1"]
    assert dropped == 1


def test_allows_multiple_tiers_when_requested():
    chunks = [
        _make_chunk("c1", "text", tier=ConfidentialityTier.STANDARD),
        _make_chunk("c2", "text", tier=ConfidentialityTier.PRIVILEGED),
    ]
    allowed, dropped = apply_access_filter(
        chunks, "t1", "matter-1", [ConfidentialityTier.STANDARD, ConfidentialityTier.PRIVILEGED]
    )
    assert len(allowed) == 2
    assert dropped == 0
