"""One-off smoke test for GeminiLLMClient against the REAL Gemini API.
Not part of the pytest suite (that stays on FakeLLMClient, no network
calls). Run manually after setting LLM_API_KEY to a real AI Studio key.
"""
import asyncio
import os

os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("LLM_MODEL", "gemini-3.1-flash-lite")

from app.llm_client.gemini_backend import GeminiLLMClient


async def main():
    if not os.environ.get("LLM_API_KEY"):
        raise SystemExit("Set LLM_API_KEY to a real aistudio.google.com key first")

    client = GeminiLLMClient()
    system_prompt = (
        'You are a legal assistant. Cite claims as [chunk_1]. If the '
        'documents do not address the question, say so exactly.'
    )
    user_prompt = (
        'Question: What is the termination notice period?\n\n'
        'Document excerpts:\n'
        '<chunk id="chunk_1" doc="Smith_Contract.pdf" page="12" section="4.2">'
        'Either party may terminate this agreement with 30 days written notice.'
        '</chunk>'
    )

    print("--- streaming response ---")
    text = ""
    async for token in client.stream_completion(system_prompt, user_prompt, max_completion_tokens=200):
        print(token, end="", flush=True)
        text += token
    print("\n--- done ---")
    print(f"completion_tokens: {client.last_completion_tokens()}")
    assert "[chunk_1]" in text, "model did not cite the chunk — check prompt/model behavior"
    print("SMOKE TEST PASSED")


asyncio.run(main())
