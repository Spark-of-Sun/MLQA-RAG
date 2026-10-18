from __future__ import annotations

import os


class LLMLinguaCompressor:
    """Real backend — LLMLingua-style prompt compression of verbose,
    boilerplate-heavy chunks while preserving specific facts/figures/dates,
    per docs/architecture.md §4 step 3. Lazily imports llmlingua so this
    module can be imported without the '[real]' extra installed.
    """

    def __init__(self, target_ratio: float | None = None):
        try:
            from llmlingua import PromptCompressor
        except ImportError as exc:
            raise RuntimeError(
                "LLMLinguaCompressor requires the 'real' extra: pip install -e '.[real]'"
            ) from exc

        self._target_ratio = target_ratio or float(os.environ.get("COMPRESSION_TARGET_RATIO", "0.5"))
        self._compressor = PromptCompressor()

    def compress(self, text: str) -> str:
        result = self._compressor.compress_prompt(text, ratio=self._target_ratio)
        return result["compressed_prompt"]
