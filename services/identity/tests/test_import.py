"""Import test for identity."""

import identity
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert identity is not None
