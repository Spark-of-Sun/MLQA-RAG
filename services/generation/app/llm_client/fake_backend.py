from __future__ import annotations


class FakeLLMClient:
    """Deterministic LLM stand-in for local unit tests and offline dev —
    never calls a real provider. Builds a canned, correctly-cited answer
    that references the FIRST chunk id found in user_prompt, so tests can
    assert the generation->citation pipeline wires chunk ids through
    correctly without needing a real API key or network access.
    """

    def __init__(self):
        self._last_completion_tokens = 0

    async def stream_completion(self, system_prompt, user_prompt, max_completion_tokens):
        import re

        chunk_ids = re.findall(r'<chunk id="([^"]+)"', user_prompt)
        cited_id = chunk_ids[0] if chunk_ids else "chunk_unknown"

        if not chunk_ids:
            text = "the provided documents do not address this"
        else:
            text = f"Based on the documents, here is the answer. [{cited_id}]"

        self._last_completion_tokens = max(1, len(text) // 4)
        for word in text.split(" "):
            yield word + " "

    def last_completion_tokens(self) -> int:
        return self._last_completion_tokens
