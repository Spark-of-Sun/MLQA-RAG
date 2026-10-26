"""Import test for citation_validator."""

import citation_validator
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert citation_validator is not None
