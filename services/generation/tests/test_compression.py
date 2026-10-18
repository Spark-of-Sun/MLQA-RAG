from __future__ import annotations

from app.compression import NoOpCompressor, WhitespaceCompressor


def test_noop_compressor_is_identity():
    text = "some   text\n\n\n\nwith gaps"
    assert NoOpCompressor().compress(text) == text


def test_whitespace_compressor_collapses_spaces_and_blank_lines():
    text = "word1     word2\n\n\n\nword3"
    result = WhitespaceCompressor().compress(text)
    assert "     " not in result
    assert "\n\n\n" not in result
    assert "word1 word2" in result
    assert "word3" in result


def test_whitespace_compressor_preserves_figures_and_dates():
    text = "The   payment   of  $12,450.00   is  due  on  2026-01-15."
    result = WhitespaceCompressor().compress(text)
    assert "$12,450.00" in result
    assert "2026-01-15" in result
