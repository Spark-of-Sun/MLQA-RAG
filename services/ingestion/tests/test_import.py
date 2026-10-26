"""Import test for ingestion."""

import ingestion
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert ingestion is not None
