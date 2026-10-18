from __future__ import annotations

import os


class GeminiLLMClient:
    """Real backend — streams from Google's Gemini API via the google-genai
    SDK. Lazily imported so this module can be imported without the
    'real' extra installed. LLM_API_KEY doubles as the Gemini API key
    when LLM_PROVIDER=gemini; set LLM_MODEL to a Gemini model name
    (e.g. gemini-2.5-flash, gemini-2.5-pro).
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "GeminiLLMClient requires the 'real' extra: pip install -e '.[real]'"
            ) from exc

        key = api_key or os.environ.get("LLM_API_KEY")
        if not key:
            raise RuntimeError("LLM_API_KEY is not set")

        self._client = genai.Client(api_key=key)
        self._model = model or os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite")
        self._last_completion_tokens = 0

    async def stream_completion(self, system_prompt, user_prompt, max_completion_tokens):
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_completion_tokens,
        )

        final_chunk = None
        async for chunk in await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=user_prompt,
            config=config,
        ):
            if chunk.text:
                yield chunk.text
            final_chunk = chunk

        # usage_metadata is only populated on the last streamed chunk.
        if final_chunk is not None and final_chunk.usage_metadata:
            self._last_completion_tokens = final_chunk.usage_metadata.candidates_token_count or 0

    def last_completion_tokens(self) -> int:
        return self._last_completion_tokens
