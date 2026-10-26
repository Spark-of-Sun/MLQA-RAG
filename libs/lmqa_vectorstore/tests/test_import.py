"""Import test for lmqa_vectorstore."""

import lmqa_vectorstore
import pytest


@pytest.mark.stage0
@pytest.mark.unit
def test_import():
    assert lmqa_vectorstore is not None
