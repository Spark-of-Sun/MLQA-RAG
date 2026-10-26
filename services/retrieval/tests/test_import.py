"""Import test for retrieval."""

import pytest
import retrieval


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert retrieval is not None
