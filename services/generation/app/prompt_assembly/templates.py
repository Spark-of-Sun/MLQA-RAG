from __future__ import annotations

from prompt_registry_client import PromptTemplate

# Matches docs/architecture.md §5 word-for-word: fixed [chunk_N] output
# format, explicit refusal instruction, closing structured citation list.
# Used whenever PromptRegistryClient has no promoted template for a
# tenant yet — which is always true until prompts/templates/ is
# populated with real versioned template files (not built yet).
DEFAULT_SYSTEM_PROMPT = """You are a legal/medical document assistant. Answer the user's \
question using ONLY the provided document excerpts below.

Rules you must follow exactly:
1. Every factual claim in your answer MUST carry an inline citation tag \
referencing the chunk it came from, in the form [chunk_ID] where ID is \
the chunk's id attribute exactly as given.
2. If the provided documents do not address the question, you MUST say \
"the provided documents do not address this" rather than guess or use \
outside knowledge.
3. End your answer with a structured citation list mapping each chunk ID \
you cited to its document, page, and section.
4. Never cite a chunk ID that was not provided to you below."""

DEFAULT_FEW_SHOT_EXAMPLES = [
    {
        "question": "What is the termination notice period?",
        "context": '<chunk id="chunk_1" doc="Smith_Contract.pdf" page="12" section="4.2">Either party may terminate this agreement with 30 days written notice.</chunk>',
        "answer": (
            "Either party may terminate the agreement with 30 days written notice [chunk_1].\n\n"
            "Citations:\n[chunk_1] Smith_Contract.pdf, page 12, section 4.2"
        ),
    },
    {
        "question": "What is the patient's history of cardiac surgery?",
        "context": '<chunk id="chunk_9" doc="Jones_ClinicalNote.pdf" page="3" section="Subjective">Patient reports occasional headaches, denies chest pain.</chunk>',
        "answer": "The provided documents do not address this.",
    },
]

DEFAULT_TEMPLATE = PromptTemplate(
    version="v0-default-builtin",
    tenant_id=None,
    system_prompt=DEFAULT_SYSTEM_PROMPT,
    few_shot_examples=DEFAULT_FEW_SHOT_EXAMPLES,
    promoted=True,
)


def get_active_template(tenant_id: str, registry_client) -> PromptTemplate:
    """Tries the real prompt registry first (prompts/templates/ once it's
    populated); falls back to DEFAULT_TEMPLATE if nothing is promoted yet
    for this tenant. Generation stays fully runnable before prompts/ is built.
    """
    try:
        return registry_client.get_active_template(tenant_id)
    except LookupError:
        return DEFAULT_TEMPLATE
