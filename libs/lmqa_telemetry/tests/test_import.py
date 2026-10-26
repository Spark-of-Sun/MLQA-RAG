"""Import test for lmqa_telemetry."""

import lmqa_telemetry
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_telemetry is not None
