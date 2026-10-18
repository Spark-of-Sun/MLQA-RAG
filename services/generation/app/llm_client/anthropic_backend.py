from __future__ import annotations

import os


class AnthropicLLMClient:
    """Real backend — streams from the Anthropic Messages API. Lazily
    imports the anthropic SDK so this module can be imported without the
    'real' extra installed. LLM_API_KEY is REQUIRED even for local
    testing against the real stack, per docs/architecture.md §6.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "AnthropicLLMClient requires the 'real' extra: pip install -e '.[real]'"
            ) from exc

        key = api_key or os.environ.get("LLM_API_KEY")
        if not key:
            raise RuntimeError("LLM_API_KEY is not set")

        self._client = anthropic.AsyncAnthropic(api_key=key)
        self._model = model or os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
        self._last_completion_tokens = 0

    async def stream_completion(self, system_prompt, user_prompt, max_completion_tokens):
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_completion_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final_message = await stream.get_final_message()
            self._last_completion_tokens = final_message.usage.output_tokens

    def last_completion_tokens(self) -> int:
        return self._last_completion_tokens

