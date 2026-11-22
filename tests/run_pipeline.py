"""Runs tests/questions.json through the retrieval + generation pipeline (planner -> retrieval -> drafter ->
verifier) and records every stage's output, for manual triage and prompt tuning.

Calls the same library code the gateway uses (GenerationService, RetrievalService, the citation validator) directly,
with the already-indexed "IPC" document in the dev database. It does NOT go through the HTTP API, does not create
chats, and writes nothing to the database: only read-only selects (document/user lookup, RLS-scoped passage reads
inside RetrievalService). Running it spends real Gemini quota: each question is roughly 5 requests (plan, embed,
re-rank, draft, verify), so 30 questions is roughly 150 requests, spread over your configured keys.

Usage:
  uv run --frozen python tests/run_pipeline.py                    # all 30 questions
  uv run --frozen python tests/run_pipeline.py --ids q01,q05,q30  # just these
  uv run --frozen python tests/run_pipeline.py --limit 5          # first 5 (quick smoke test)
  uv run --frozen python tests/run_pipeline.py --compare tests/results/baseline.json   # before/after table
  uv run --frozen python tests/run_pipeline.py --out tests/results/baseline.json       # name the output file

Grading, per question:
  "answer" case   PASS if the released answer (after the citation validator and entailment) cites at least one
                   source whose text contains one of expected_sections, and does not cite one in must_not_cite.
  "refuse" case    PASS if the released answer is nothing but the canonical refusal (no sentence, no citation).

Stage attribution for a FAIL (evidence-based, never a guess):
  retrieval      the right section's passage was never among the kept/candidate passages retrieval returned
                 (checked against retrieval's own `dropped` list and its reason, when the passage was a candidate)
  drafting       the passage was available to the drafter (it was a source), but the draft did not cite it, cited
                 the wrong thing, or (for a refuse case) answered when it should not have
  verification   the drafter did cite the right source, but a deterministic check (V1-V8) or entailment (V6)
                 removed that sentence before release; the removal's own code and reason are reported
  error          a provider/model error stopped the question before a verdict was reached (not a prompt issue)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Test configuration, the same for every run so before/after counts compare prompts, not models. Applied to this
# process only (the process environment overrides .env); .env and the running app are not changed.
#   - one model for every stage, no fallbacks: a run never silently switches model mid-way. gemini-3.1-flash-lite
#     answered in 1.8 s when tested and has the largest daily quota (500 a day per key).
#   - gemini-2.5-flash and gemini-2.5-flash-lite return 404 "no longer available to new users" on every key.
#   - thinking "low": with "high", re-ranking 40 passages ran out of output tokens (MAX_TOKENS) on q01.
TEST_CONFIG = {
    "LLM_MODEL": "gemini-3.1-flash-lite",
    "LLM_FALLBACK_MODELS": "gemini-3.1-flash-lite",  # same model: an empty value would fall back to .env
    "QUERY_MODEL": "gemini-3.1-flash-lite",
    "QUERY_FALLBACK_MODELS": "none",
    "RERANK_LLM_MODELS": "gemini-3.1-flash-lite",
    "LLM_THINKING_LEVEL": "low",
}
os.environ.update(TEST_CONFIG)
RETRIES = 2  # a question that hits a provider error (503, timeout) is retried after a pause, then recorded as error
RETRY_PAUSE_S = 30

from citation_validator import apply_entailment, build_result, entailment_claims, validate  # noqa: E402
from generation import GenerationService, LLMError  # noqa: E402
from lmqa_db import Database  # noqa: E402
from lmqa_models.principal import Membership, Principal  # noqa: E402
from lmqa_models.quota import question as quota_question  # noqa: E402
from lmqa_models.settings import load_settings  # noqa: E402
from retrieval import EmbeddingError, create_retrieval  # noqa: E402

QUESTIONS_FILE = ROOT / "tests" / "questions.json"
RESULTS_DIR = ROOT / "tests" / "results"
RETRIEVAL_HEADROOM_TOKENS = 1500

# The user who owns the indexed "IPC" document in this dev database (see tests/questions.json's header). Change
# this if you run the suite against a different workspace or document.
DOCUMENT_OWNER_SUB = "google-oauth2|118140465854412164325"


# ------------------------------------------------------------------------------------------------- read-only setup
def load_owner_principal(db: Database, sub: str) -> Principal:
    """The indexed document's owner, read-only (a plain select; no insert, no last_seen_at bump)."""
    with db.system() as conn:
        user = conn.execute("select id, email, name from users where auth0_sub = %s", [sub]).fetchone()
        if user is None:
            raise SystemExit(f"No user with auth0_sub={sub!r}. Edit DOCUMENT_OWNER_SUB in tests/run_pipeline.py.")
        row = conn.execute(
            "select m.id, m.role, m.status, m.org_id, o.name as org_name, o.kind as org_kind,"
            " o.status as org_status, m.workspace_id, w.name as workspace_name, w.status as workspace_status"
            " from memberships m join organizations o on o.id = m.org_id"
            " left join workspaces w on w.id = m.workspace_id"
            " where m.user_id = %s and m.status <> 'rejected' order by m.created_at desc limit 1",
            [user["id"]],
        ).fetchone()
    if row is None:
        raise SystemExit(f"User {sub!r} has no active membership.")
    membership = Membership(
        id=str(row["id"]),
        role=row["role"],
        status=row["status"],
        org_id=str(row["org_id"]),
        org_name=row["org_name"],
        org_kind=row["org_kind"],
        org_status=row["org_status"],
        workspace_id=str(row["workspace_id"]) if row["workspace_id"] else None,
        workspace_name=row["workspace_name"],
        workspace_status=row["workspace_status"],
    )
    return Principal(str(user["id"]), sub, user["email"], user["name"], membership)


# ------------------------------------------------------------------------------------------------- grading
_SECTION_BODY = {}  # secnum -> compiled pattern, cached


def _pattern(secnum: str) -> re.Pattern[str]:
    if secnum not in _SECTION_BODY:
        _SECTION_BODY[secnum] = re.compile(re.escape(secnum) + r"\.\s?[A-Za-z]")
    return _SECTION_BODY[secnum]


def sections_in(text: str) -> set[str]:
    """Which of the sections tests/questions.json refers to appear (as '<n>. <Title>') in this passage text."""
    return {s for s in _SECTION_BODY_UNIVERSE if _pattern(s).search(text)}


_SECTION_BODY_UNIVERSE: set[str] = set()  # filled in main() from every question's expected_sections/must_not_cite


# ------------------------------------------------------------------------------------------------- one question
def run_one(generation: GenerationService, retrieval: Any, principal: Principal, settings: Any, q: dict) -> dict:
    out: dict[str, Any] = {"id": q["id"], "question": q["question"]}
    t_start = time.monotonic()
    ledger: dict[str, Any] = {}
    try:
        with quota_question(settings.quota()):
            plan = generation.plan_query([], q["question"], expand=settings.query_expansion)
            out["planner"] = {
                "corrected_question": plan.question,
                "queries": plan.alternatives,
                "detail_note": plan.detail_note,
                "model": plan.model,
            }

            found = retrieval.retrieve(
                principal,
                plan.question,
                alternatives=plan.alternatives,
                budget_tokens=settings.context_budget_tokens - RETRIEVAL_HEADROOM_TOKENS,
            )
            out["retrieval"] = {
                "kept": [
                    {
                        "alias": s.alias,
                        "section_heading": s.section,
                        "sections_found": sorted(sections_in(s.text)),
                        "score": round(s.score, 3),
                        "text_preview": s.text[:160],
                    }
                    for s in found.sources
                ],
                "dropped": [{"reason": d.reason, "score": round(d.score, 3)} for d in found.dropped],
                "stats": found.stats,
            }

            if not found.sources:
                result = build_result(False, [], {})
            else:
                draft = generation.draft(
                    q["question"], found.sources, standalone=plan.question, detail_note=plan.detail_note
                )
                out["draft"] = {
                    "model": draft.model,
                    "answerable": draft.data.get("answerable"),
                    "sentences": [
                        {"text": s.get("text"), "citations": [c.get("source") for c in s.get("citations", [])]}
                        for s in draft.data.get("sentences", [])
                        if isinstance(s, dict)
                    ],
                }
                ledger = {s.alias: s for s in draft.sources}
                answerable, verdicts = validate(draft.data, ledger, entailment=settings.verify_entailment)
                if settings.verify_entailment:
                    check = generation.entailment(entailment_claims(verdicts), ledger)
                    apply_entailment(verdicts, check.verdicts)
                out["verifier"] = {
                    "removed": [
                        {"text": v.text, "aliases": v.aliases, "reason": v.first_failure} for v in verdicts if not v.ok
                    ]
                }
                result = build_result(answerable, verdicts, ledger)
    except (LLMError, EmbeddingError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["latency_s"] = round(time.monotonic() - t_start, 1)
        return out

    chunk_id_to_alias = {s.chunk_id: a for a, s in ledger.items()}
    out["citation_alias_map"] = {c["n"]: chunk_id_to_alias.get(c["chunk_id"]) for c in result.get("citations", [])}
    out["_ledger_sections"] = {a: sorted(sections_in(s.text)) for a, s in ledger.items()}
    out["result"] = {
        "outcome": result["outcome"],
        "segments": [{k: v for k, v in seg.items() if k != "checks"} for seg in result["segments"]],
    }
    out["latency_s"] = round(time.monotonic() - t_start, 1)
    grade(out, q)
    return out


def grade(out: dict, q: dict) -> None:
    """Fills out['pass'] and out['stage']/out['why'] on failure. Evidence-based: cites the actual data above."""
    if "error" in out:
        out["pass"], out["stage"], out["why"] = False, "error", out["error"]
        return

    expected = set(q["expected_sections"])
    forbidden = set(q["must_not_cite"])
    released = out["result"]["segments"]
    cited_sections: set[str] = set()
    for seg in released:
        if seg.get("type") == "sentence":
            for n in seg.get("citations", []):
                alias = out["citation_alias_map"].get(n)
                if alias:
                    cited_sections |= set(out["_ledger_sections"].get(alias, []))

    if q["expected_behavior"] == "refuse":
        only_refused = out["result"]["outcome"] == "refused" and not any(s.get("type") == "sentence" for s in released)
        if only_refused:
            out["pass"] = True
            return
        out["pass"] = False
        out["stage"] = "drafting"
        cites = sorted(cited_sections) or "(none resolvable)"
        out["why"] = f"expected a refusal; the drafter produced content instead, citing sections {cites}"
        return

    # expected_behavior == "answer"
    if forbidden & cited_sections:
        out["pass"] = False
        out["stage"] = "drafting"
        out["why"] = f"cited a section that must not apply here: {sorted(forbidden & cited_sections)}"
        return
    if expected & cited_sections:
        out["pass"] = True
        return

    out["pass"] = False
    retrieved_sections = {s for row in out["retrieval"]["kept"] for s in row["sections_found"]}
    if not (expected & retrieved_sections):
        out["stage"] = "retrieval"
        dropped_reasons = sorted({d["reason"] for d in out["retrieval"]["dropped"]})
        out["why"] = (
            f"none of the kept {len(out['retrieval']['kept'])} passages contain sections {sorted(expected)}; "
            f"dropped-passage reasons seen this question: {dropped_reasons or '(nothing was dropped either)'}"
        )
        return
    if "draft" in out and not out["draft"]["sentences"]:
        out["stage"] = "drafting"
        out["why"] = (
            f"the right section was retrieved (in kept passages: {sorted(expected & retrieved_sections)}), "
            f"but the drafter wrote no cited sentences (answerable={out['draft']['answerable']})"
        )
        return
    removed = out.get("verifier", {}).get("removed", [])
    matching_removed = []
    for r in removed:
        removed_secs = {s for a in r["aliases"] for s in out["_ledger_sections"].get(a, [])}
        if expected & removed_secs:
            matching_removed.append(r)
    if matching_removed:
        out["stage"] = "verification"
        out["why"] = f"a sentence citing the right section was removed: {matching_removed[0]['reason']!r}"
        return
    out["stage"] = "drafting"
    draft_cites = sorted({a for s in out.get("draft", {}).get("sentences", []) for a in s["citations"]})
    out["why"] = (
        f"the right section was retrieved ({sorted(expected & retrieved_sections)}) but the released answer "
        f"does not cite it; the draft cited {draft_cites}"
    )


# ------------------------------------------------------------------------------------------------- driver
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", help="comma-separated question ids to run, e.g. q01,q05,q30")
    ap.add_argument("--limit", type=int, help="only run the first N questions (after --ids filtering)")
    ap.add_argument("--out", type=Path, help="where to save results (default: tests/results/<timestamp>.json)")
    ap.add_argument("--compare", type=Path, help="a previous results file to diff against")
    args = ap.parse_args()

    data = json.loads(QUESTIONS_FILE.read_text())
    questions = data["questions"]
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        print("No questions selected.")
        return 1

    global _SECTION_BODY_UNIVERSE
    _SECTION_BODY_UNIVERSE = {s for q in data["questions"] for s in q["expected_sections"] + q["must_not_cite"]}

    settings = load_settings()
    db = Database(settings)
    db.open()
    try:
        principal = load_owner_principal(db, DOCUMENT_OWNER_SUB)
        generation = GenerationService(settings)
        retrieval = create_retrieval(settings, db, generation.reranker)

        results = []
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}: {q['question'][:70]}", flush=True)
            r = run_one(generation, retrieval, principal, settings, q)
            for _attempt in range(RETRIES):
                if "error" not in r:
                    break
                print(f"    provider error ({r['error'][:90]}); retrying in {RETRY_PAUSE_S}s", flush=True)
                time.sleep(RETRY_PAUSE_S)
                r = run_one(generation, retrieval, principal, settings, q)
            results.append(r)
            status = "PASS" if r.get("pass") else ("ERROR" if "error" in r else f"FAIL ({r.get('stage')})")
            print(f"    -> {status}  ({r['latency_s']}s)", flush=True)
    finally:
        db.close()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.out or RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    from generation.prompts import load_prompts

    prompts = load_prompts()
    meta = {"test_config": TEST_CONFIG, "prompt_versions": prompts.versions, "prompt_sha256": prompts.sha256}
    out_path.write_text(json.dumps({"meta": meta, "questions": results}, indent=2, default=str))
    print(f"\nSaved {out_path}")

    print_summary(results)
    if args.compare:
        print_comparison(json.loads(args.compare.read_text())["questions"], results, args.compare, out_path)
    return 0


def print_summary(results: list[dict]) -> None:
    passed = sum(r.get("pass") is True for r in results)
    failed = [r for r in results if r.get("pass") is not True]
    print(f"\n{passed}/{len(results)} passed.")
    if failed:
        by_stage: dict[str, list[str]] = {}
        for r in failed:
            by_stage.setdefault(r.get("stage", "error"), []).append(r["id"])
        for stage, ids in sorted(by_stage.items()):
            print(f"  {stage}: {', '.join(ids)}")
        print("\nFailure detail:")
        for r in failed:
            print(f"  {r['id']} [{r.get('stage', 'error')}] {r['question'][:60]!r}")
            print(f"      {r.get('why', r.get('error'))}")


def print_comparison(before: list[dict], after: list[dict], before_path: Path, after_path: Path) -> None:
    before_by_id = {r["id"]: r for r in before}
    print(f"\nBefore ({before_path.name}) -> after ({after_path.name}):")
    b_pass = sum(r.get("pass") is True for r in before)
    a_pass = sum(r.get("pass") is True for r in after)
    print(f"  total pass: {b_pass}/{len(before)} -> {a_pass}/{len(after)}")
    changed = []
    for r in after:
        b = before_by_id.get(r["id"])
        if b is None:
            continue
        b_status = "PASS" if b.get("pass") else b.get("stage", "error")
        a_status = "PASS" if r.get("pass") else r.get("stage", "error")
        if b_status != a_status:
            changed.append((r["id"], b_status, a_status))
    if changed:
        print("  changed:")
        for qid, b_status, a_status in changed:
            arrow = "improved" if a_status == "PASS" else ("regressed" if b_status == "PASS" else "changed")
            print(f"    {qid}: {b_status} -> {a_status}  ({arrow})")
    else:
        print("  no question changed status.")


if __name__ == "__main__":
    sys.exit(main())
