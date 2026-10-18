from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from pydantic import BaseModel


class PromptTemplate(BaseModel):
    """A single versioned prompt template, per docs/architecture.md §5.
    system_prompt fixes the [chunk_N] output format and the refusal
    instruction; few_shot_examples must include at least one correct
    refusal, enforced by prompts/eval_sets/.
    """

    version: str
    tenant_id: str | None = None  # None = default template for all tenants
    system_prompt: str
    few_shot_examples: list[dict]
    promoted: bool = False


class PromptRegistryClient:
    """Backend is selected via PROMPT_REGISTRY_BACKEND:
      - "local-file": reads versioned JSON files from prompts/templates/
        (default; what local dev and CI use)
      - "promptlayer" / "langfuse": calls the hosted registry's API

    Generation calls get_active_template() once per request (cached by the
    caller) rather than per-token, to keep the token-budget hot path fast.
    """

    def __init__(
        self,
        backend: str | None = None,
        templates_dir: str | Path = "prompts/templates",
        api_key: str | None = None,
    ) -> None:
        self.backend = backend or os.environ.get("PROMPT_REGISTRY_BACKEND", "local-file")
        self.templates_dir = Path(templates_dir)
        self.api_key = api_key or os.environ.get("PROMPT_REGISTRY_API_KEY")

    def get_active_template(self, tenant_id: str) -> PromptTemplate:
        if self.backend == "local-file":
            return self._get_active_template_local(tenant_id)
        return self._get_active_template_remote(tenant_id)

    def _get_active_template_local(self, tenant_id: str) -> PromptTemplate:
        candidates: list[PromptTemplate] = []
        for path in sorted(self.templates_dir.glob("*.json")):
            data = json.loads(path.read_text())
            template = PromptTemplate(**data)
            if template.promoted and template.tenant_id in (None, tenant_id):
                candidates.append(template)

        if not candidates:
            raise LookupError(f"no promoted prompt template found for tenant={tenant_id}")

        # Tenant-specific override wins over the global default.
        candidates.sort(key=lambda t: t.tenant_id == tenant_id, reverse=True)
        return candidates[0]

    def _get_active_template_remote(self, tenant_id: str) -> PromptTemplate:
        base_url = {
            "promptlayer": "https://api.promptlayer.com",
            "langfuse": "https://cloud.langfuse.com/api/public",
        }[self.backend]

        response = httpx.get(
            f"{base_url}/prompts/active",
            params={"tenant_id": tenant_id},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=5.0,
        )
        response.raise_for_status()
        return PromptTemplate(**response.json())

    def record_eval_result(
        self, template_version: str, pass_rate: float, question_count: int
    ) -> None:
        """Called by scripts/run_citation_eval.py after each eval run, so a
        template's citation-validation pass rate is visible before it's
        promoted to production (docs/architecture.md §9, milestone 7)."""
        if self.backend == "local-file":
            log_path = self.templates_dir / "eval_history.jsonl"
            with log_path.open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "template_version": template_version,
                            "pass_rate": pass_rate,
                            "question_count": question_count,
                        }
                    )
                    + "\n"
                )
            return

        base_url = {
            "promptlayer": "https://api.promptlayer.com",
            "langfuse": "https://cloud.langfuse.com/api/public",
        }[self.backend]
        httpx.post(
            f"{base_url}/prompts/{template_version}/eval-results",
            json={"pass_rate": pass_rate, "question_count": question_count},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=5.0,
        )
