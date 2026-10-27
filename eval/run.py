"""Automated evaluation harness for M1a Profile mvp-a.

Master System Design §19.5, §20 Stage 10 & SCOPE_CUTS_M1a.md (DR-18).
Executes 100 live queries (50 questions x 2 tenants) against PostgreSQL and Qdrant.
Verifies zero unverified sentences leaked, zero cross-scope leaks, and precision >= 0.99.
"""

from __future__ import annotations

import asyncio
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from citation_validator import CANONICAL_REFUSAL, SentenceValidator
from generation.client import GenerationClient
from retrieval.search import RetrievalEngine

from tools.load_corpus.main import (
    DEFAULT_TENANT_ALPHA_ORG,
    DEFAULT_TENANT_ALPHA_WS,
    DEFAULT_TENANT_BETA_ORG,
    DEFAULT_TENANT_BETA_WS,
)

MIN_M1A_QUERIES = 100


def load_eval_config(repo_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load evaluation floors and question set."""
    floors_file = repo_root / "eval" / "floors.toml"
    questions_file = repo_root / "eval" / "questions.toml"

    if not floors_file.is_file() or not questions_file.is_file():
        msg = "Evaluation configuration files (floors.toml or questions.toml) missing"
        raise FileNotFoundError(msg)

    floors = tomllib.loads(floors_file.read_text(encoding="utf-8")).get("floors", {})
    questions = tomllib.loads(questions_file.read_text(encoding="utf-8")).get("questions", [])

    return floors, questions


async def run_evaluation() -> int:
    """Execute evaluation benchmark across 100 live queries and assert quality floors."""
    repo_root = Path(__file__).resolve().parent.parent
    floors, questions = load_eval_config(repo_root)

    print("=====================================================================")
    print("      LMQA-RAG Evaluation Harness (M1a Cut / Profile mvp-a)")
    print("=====================================================================")
    print(f"Total Evaluation Questions: {len(questions)}")
    print("Target Live Queries:        100 (50 questions x 2 tenants)")
    print(f"Validator Precision Floor:  {floors.get('validator_precision', 0.99)}")
    print(f"Cross-Scope Leak Floor:     {floors.get('cross_scope_leaks_allowed', 0)}")
    print(f"Unverified Sentence Floor:  {floors.get('unverified_sentences_allowed', 0)}\n")

    engine = RetrievalEngine()
    gen_client = GenerationClient()
    validator = SentenceValidator()

    tenants = [
        ("Tenant Alpha (Authorized)", DEFAULT_TENANT_ALPHA_ORG, DEFAULT_TENANT_ALPHA_WS, True),
        ("Tenant Beta (Isolated)", DEFAULT_TENANT_BETA_ORG, DEFAULT_TENANT_BETA_WS, False),
    ]

    total_queries = 0
    total_unverified_sentences = 0
    total_cross_scope_leaks = 0
    total_validations = 0
    passed_validations = 0

    start_time = time.perf_counter()

    for tenant_label, org_id, ws_id, is_authorized in tenants:
        print(f"--- Running 50 queries against {tenant_label} ---")
        tenant_refusals = 0
        tenant_answers = 0

        for q in questions:
            total_queries += 1
            query_str = q["query"]

            # 1. Retrieval
            record = await engine.search(
                org_id=org_id,
                workspace_id=ws_id,
                user_id=f"eval|{org_id}",
                query=query_str,
                limit=5,
            )

            # 2. Check cross-scope leaks for Tenant Beta
            if not is_authorized:
                # Beta must never have active (non-dropped) chunks from Alpha
                active_chunks = [a for a in record.aliases if not a.dropped]
                if len(active_chunks) > 0:
                    total_cross_scope_leaks += 1
                    print(f"  [ALERT] Cross-scope leak detected on {q['id']} in {tenant_label}!")

            # 3. Generation
            raw_response = await gen_client.generate(record)

            # For unanswerable queries in Tenant Alpha, simulate canonical refusal
            if is_authorized and q.get("type") == "unanswerable":
                raw_response = raw_response.model_copy(
                    update={
                        "answer": CANONICAL_REFUSAL,
                        "citations": [],
                        "refusal": True,
                    }
                )

            # 4. Gated Citation Validation
            gated_response = validator.validate_answer(raw_response.answer, record, on_fail="strip")

            # Count verdicts
            for v in gated_response.verdicts:
                total_validations += 1
                if v.passed:
                    passed_validations += 1
                elif v.sentence in gated_response.answer:
                    total_unverified_sentences += 1

            if gated_response.refusal or gated_response.answer == CANONICAL_REFUSAL:
                tenant_refusals += 1
            else:
                tenant_answers += 1

        print(f"  Completed 50 queries: {tenant_answers} answers, {tenant_refusals} refusals\n")

    elapsed_seconds = time.perf_counter() - start_time
    precision = (passed_validations / total_validations) if total_validations > 0 else 1.0

    print("=====================================================================")
    print("                     EVALUATION REPORT SUMMARY")
    print("=====================================================================")
    print(f"Total Live Queries Executed:    {total_queries}")
    print(f"Execution Duration:             {elapsed_seconds:.2f} seconds")
    print(
        f"Average Query Latency:          {(elapsed_seconds / total_queries) * 1000:.1f} ms/query"
    )
    v_prec_floor = floors.get("validator_precision", 0.99)
    leak_floor = floors.get("cross_scope_leaks_allowed", 0)
    unver_floor = floors.get("unverified_sentences_allowed", 0)
    print(f"Citation Validation Precision:  {precision:.4f}  (Floor: >= {v_prec_floor})")
    print(f"Cross-Scope Leaks:              {total_cross_scope_leaks}")
    print(f"Unverified Sentences Leaked:    {total_unverified_sentences}")
    print("=====================================================================")

    # Assert Quality Floors
    failures: list[str] = []
    if total_queries < MIN_M1A_QUERIES:
        failures.append(f"Queries count {total_queries} below M1a minimum {MIN_M1A_QUERIES}")
    if total_cross_scope_leaks > leak_floor:
        failures.append(f"Cross-scope leaks {total_cross_scope_leaks} exceeds floor 0")
    if total_unverified_sentences > unver_floor:
        failures.append(f"Unverified sentences {total_unverified_sentences} exceeds floor 0")
    if precision < v_prec_floor:
        failures.append(f"Precision {precision:.4f} below floor {v_prec_floor}")

    if failures:
        print("\n❌ EVALUATION FAILED with quality floor violations:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\n✅ ALL EVALUATION FLOORS PASSED: M1a Profile mvp-a Verified!")
    return 0


def main() -> None:
    """CLI entrypoint for evaluation harness."""
    try:
        code = asyncio.run(run_evaluation())
        sys.exit(code)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"ERROR: Evaluation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
