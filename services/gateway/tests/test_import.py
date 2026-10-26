"""Import test for gateway."""

import gateway
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert gateway is not None
