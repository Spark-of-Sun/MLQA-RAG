"""Retrieval evaluation harness (blueprint 11.3, 11.7, 19): `make eval`.

Indexes the public corpus once into a separate `lmqa_eval` database (through the real onboarding and upload API,
so parsing, chunking and embedding are the production code), then runs every case in eval/sets/ through the
retrieval service in three configurations and reports standard retrieval metrics:

  fused   hybrid search only (dense + full text + exact terms, reciprocal rank fusion)
  rerank  + cross-encoder re-ranking and the relevance threshold
  full    + query expansion and neighbour expansion: the pipeline as configured for production

Metrics (answerable cases; a case is a hit when a passage containing its labelled text is kept for the answer):
  recall@k  share of cases with a hit among the kept passages (k = RETRIEVAL_TOP_K)
  hit@1     share of cases whose first kept passage is a hit
  MRR       mean reciprocal rank of the first hit
  nDCG@k    binary-relevance nDCG of the first hit
  abstain   share of unanswerable cases for which nothing passes the threshold (no model call is made)

The `full` configuration is compared with eval/floors.toml; the exit code is 1 below a floor. With --answers each
case is also asked end to end (answer model, citation validator) and answer-level outcomes are reported.
Passage embeddings are cached per organization, so re-running costs only the query embeddings.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import tomllib
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import demo  # noqa: E402  (tools/demo.py: colours)
from fastapi.testclient import TestClient  # noqa: E402
from real_identity import Identity, load  # noqa: E402  (real Auth0 accounts, R-27)

from gateway.app import create_app  # noqa: E402
from lmqa_db import Claims  # noqa: E402
from lmqa_db.migrate import drop_database, migrate  # noqa: E402
from lmqa_keys import Field  # noqa: E402
from lmqa_models.envfile import ROOT  # noqa: E402
from lmqa_models.settings import load_settings  # noqa: E402
from retrieval import RetrievalService  # noqa: E402

EVAL_DB = "lmqa_eval"
EVAL_DIR = ROOT / "eval"
CORPUS = ROOT / "corpus" / "data"
RESULTS = ROOT / "data" / "eval" / "results"
OWNER = "eval-owner"  # auth harness labels of real Auth0 accounts
SUFFIX = {
    "pdf": ".pdf",
    "html": ".htm",
    "xml": ".xml",
    "jats": ".xml",
    "spl": ".xml",
    "docx": ".docx",
    "txt": ".txt",
}
ADMIN = "eval-admin"
B, G, R, Y, D, X = demo.B, demo.G, demo.R, demo.Y, demo.D, demo.X


class Client:
    def __init__(self, client: TestClient, who: Identity) -> None:
        self.client = client
        self.headers = who.headers

    def get(self, path: str) -> Any:
        return self.client.get(f"/v1{path}", headers=self.headers).json()

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.client.post(f"/v1{path}", headers=self.headers, json=body or {})


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def ensure_corpus(  # noqa: C901 - one linear flow; splitting it is a DEV-33 follow-up
    client: TestClient, idp: dict[str, Identity], manifest: list[dict[str, Any]]
) -> Client:
    """Organization, approved admin and every corpus document indexed. Idempotent."""
    owner, admin = Client(client, idp[OWNER]), Client(client, idp[ADMIN])
    if owner.get("/me")["membership"] is None:
        owner.post("/onboarding/organization", {"name": "Evaluation", "kind": "both"})
    if admin.get("/me")["membership"] is None:
        code = owner.post("/org/code").json()["code"]
        admin.post("/onboarding/join-admin", {"code": code, "workspace_name": "Corpus"})
        pending = [a for a in owner.get("/org/admins") if a["status"] == "pending"]
        for a in pending:
            owner.post(f"/org/admins/{a['id']}/approve")
    docs = {d["filename"]: d for d in admin.get("/documents")}
    for item in manifest:
        name = item["file"]
        if name in docs and docs[name]["status"] == "failed":
            client.delete(f"/v1/documents/{docs[name]['id']}", headers=admin.headers)
            docs.pop(name)
        if name not in docs:
            data = (CORPUS / name).read_bytes()
            r = client.post(
                "/v1/documents",
                headers=admin.headers,
                files={"file": (name, data)},
                data={"visibility": "private", "title": item["title"][:200]},
            )
            if r.status_code != 201:
                print(f"   {R}upload failed: {name}: {r.text[:200]}{X}")
    started = time.monotonic()
    while True:
        docs = {d["filename"]: d for d in admin.get("/documents")}
        pending = [n for n, d in docs.items() if d["status"] == "processing"]
        if not pending:
            break
        if time.monotonic() - started > 3600:
            print(f"   {R}still indexing after an hour: {', '.join(pending)}{X}")
            break
        print(f"   {D}indexing {len(pending)} document(s)…{X}", flush=True)
        time.sleep(10)
    failed = {n: d.get("error") for n, d in docs.items() if d["status"] != "ready"}
    for n, err in failed.items():
        print(f"   {R}not indexed: {n}: {err}{X}")
    ready = sum(d["status"] == "ready" for d in docs.values())
    chunks = sum(d.get("chunk_count") or 0 for d in docs.values())
    print(f"   corpus: {ready}/{len(manifest)} documents ready, {chunks} passages")
    return admin


def relevant_ids(
    svc: Any, cases: list[dict[str, Any]], admin_sub: str
) -> dict[str, list[set[str]]]:
    """case id -> one set of chunk ids per expected answer (any chunk of a set satisfies it)."""
    with svc.db.as_service("identity", Claims(actor="eval")) as conn:
        owner = conn.execute("select id from users where auth0_sub = %s", [admin_sub]).fetchone()
    by_file: dict[str, list[tuple[str, str]]] = {}
    if owner is None:
        return {c["id"]: [set() for _ in c.get("expect", [])] for c in cases}
    # Text and file names are sealed (lmqa_keys): read as the admin under RLS, then open them.
    with svc.db.scoped(str(owner["id"])) as scope:
        rows = scope.execute(
            "select c.id, c.org_id, c.workspace_id, c.document_id, c.version, c.text_ct, d.filename_ct"
            " from chunks c join documents d on d.id = c.document_id where d.owner_id = %s",
            [owner["id"]],
        ).fetchall()
        for r in rows:
            chunk = svc.keys.open_chunk_row(scope, dict(r))
            filename = svc.keys.open(
                scope,
                Field.document(
                    "document.filename", r["org_id"], r["workspace_id"], r["document_id"]
                ),
                r["filename_ct"],
            )
            by_file.setdefault(str(filename), []).append((str(r["id"]), norm(chunk["text"])))
    out: dict[str, list[set[str]]] = {}
    for c in cases:
        out[c["id"]] = [
            {cid for cid, text in by_file.get(e["file"], []) if norm(e["contains"]) in text}
            for e in c.get("expect", [])
        ]
    return out


def evaluate(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
    name: str,
    service: RetrievalService,
    principal: Any,
    cases: list[dict[str, Any]],
    relevant: dict[str, list[set[str]]],
    plans: dict[str, list[str]],
    budget: int,
) -> dict[str, Any]:
    rows = []
    for c in cases:
        found = service.retrieve(
            principal, c["question"], alternatives=plans.get(c["id"], []), budget_tokens=budget
        )
        ids = [s.chunk_id for s in found.sources]
        groups = relevant[c["id"]]
        ranks = [next((i for i, cid in enumerate(ids, start=1) if cid in g), None) for g in groups]
        first = min((r for r in ranks if r is not None), default=None)
        rows.append(
            {
                "id": c["id"],
                "answerable": bool(groups),
                "kept": len(ids),
                "rank": first,
                "top": [
                    f"{s.document_title[:40]} · {(s.section or '')[-40:]} ({s.score})"
                    for s in found.sources[:3]
                ],
                **{k: v for k, v in found.stats.items() if k.endswith("_ms")},
            }
        )
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    n = max(len(answerable), 1)
    metrics = {
        "recall_at_k": sum(r["rank"] is not None for r in answerable) / n,
        "hit_at_1": sum(r["rank"] == 1 for r in answerable) / n,
        "mrr": sum(1 / r["rank"] for r in answerable if r["rank"]) / n,
        "ndcg_at_k": sum(1 / math.log2(r["rank"] + 1) for r in answerable if r["rank"]) / n,
        "abstention": sum(r["kept"] == 0 for r in unanswerable) / max(len(unanswerable), 1),
        "avg_kept": sum(r["kept"] for r in answerable) / n,
    }
    for key in ("embed_ms", "search_ms", "rerank_ms"):
        metrics[key] = int(sum(r.get(key, 0) for r in rows) / max(len(rows), 1))
    return {"config": name, "metrics": metrics, "cases": rows}


def answer_eval(
    client: TestClient,
    idp: dict[str, Identity],
    cases: list[dict[str, Any]],
    relevant: dict[str, list[set[str]]],
) -> dict[str, Any]:
    """End to end: answerable cases should get verified sentences citing a labelled passage; unanswerable ones the
    refusal. Uses the answer model (about three calls per case)."""
    admin = Client(client, idp[ADMIN])
    out = {
        "answered_with_cited_answer": 0,
        "answerable": 0,
        "refused_correctly": 0,
        "unanswerable": 0,
        "removed": 0,
        "verified": 0,
    }
    for c in cases:
        r = admin.post("/queries", {"question": c["question"]})
        if r.status_code != 200:
            print(f"   {R}{c['id']}: HTTP {r.status_code} {r.text[:160]}{X}")
            continue
        res = r.json()
        stats = res.get("stats", {})
        out["verified"] += stats.get("verified", 0)
        out["removed"] += stats.get("removed", 0)
        cited = {cit["chunk_id"] for cit in res.get("citations", [])}
        if relevant[c["id"]]:
            out["answerable"] += 1
            if stats.get("verified", 0) and any(cited & g for g in relevant[c["id"]]):
                out["answered_with_cited_answer"] += 1
        else:
            out["unanswerable"] += 1
            if not stats.get("verified", 0):
                out["refused_correctly"] += 1
    return out


def main() -> int:  # noqa: C901, PLR0912, PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", default="sets/corpus.toml")
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="drop the lmqa_eval database and index the corpus again",
    )
    ap.add_argument(
        "--no-llm", action="store_true", help="skip query expansion (no answer-model calls)"
    )
    ap.add_argument("--answers", action="store_true", help="also ask every case end to end")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    args = ap.parse_args()

    base = load_settings()
    if not base.gemini_api_key:
        print("GEMINI_API_KEY is not set; the evaluation needs it for embeddings.")
        return 1
    manifest = tomllib.loads((ROOT / "corpus" / "manifest.toml").read_text())["item"]
    for item in manifest:  # file names as written by corpus/fetchers.py
        item["file"] = f"{item['id']}{SUFFIX.get(item['format'], '')}"
    missing = [i["file"] for i in manifest if not (CORPUS / i["file"]).is_file()]
    if missing:
        print(f"Missing corpus files ({len(missing)}). Run: make corpus")
        return 1
    cases = tomllib.loads((EVAL_DIR / args.set).read_text())["case"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    floors = tomllib.loads((EVAL_DIR / "floors.toml").read_text())["retrieval"]

    idp = load([OWNER, ADMIN], base.auth0_claims_namespace)
    settings = base.with_overrides(
        db_name=EVAL_DB,
        data_dir=ROOT / "data" / "eval" / "objects",
    )
    print(f"{B}Retrieval evaluation{X}  {D}database={EVAL_DB} set={args.set} cases={len(cases)}{X}")
    if args.rebuild:
        drop_database(settings, EVAL_DB)
    migrate(settings, EVAL_DB)

    app = create_app(settings, resume_jobs=True)
    with TestClient(app) as client:
        svc = app.state.services
        ensure_corpus(client, idp, manifest)
        principal = svc.identity.resolve(idp[ADMIN].sub, idp[ADMIN].email, idp[ADMIN].name)
        relevant = relevant_ids(svc, cases, idp[ADMIN].sub)
        unlabelled = [c["id"] for c in cases if c.get("expect") and not all(relevant[c["id"]])]
        if unlabelled:
            print(
                f"   {Y}labels with no matching passage (corpus or chunking changed?): {', '.join(unlabelled)}{X}"
            )

        plans: dict[str, list[str]] = {}
        if settings.query_expansion and not args.no_llm:
            for c in cases:
                plans[c["id"]] = svc.generation.plan_query(
                    [], c["question"], expand=True
                ).alternatives

        reranker = svc.retrieval.reranker
        if reranker is not None and reranker.local:
            reranker.score(
                "warm-up", ["warm-up"]
            )  # load the local model before timing (an LLM needs no warm-up)
        budget = settings.context_budget_tokens - 1500
        variants = [
            ("fused", replace(settings, rerank_model=None, retrieval_neighbors=0), {}),
            ("rerank", replace(settings, retrieval_neighbors=0), {}),
            ("full", settings, plans),
        ]
        reports = []
        for name, s, case_plans in variants:
            if name != "fused" and reranker is None:
                continue
            service = RetrievalService(
                s, svc.db, svc.retrieval._embedder, svc.keys
            )  # share one embedding client
            service.reranker = reranker if s.rerank_model else None
            reports.append(evaluate(name, service, principal, cases, relevant, case_plans, budget))

        print(
            f"\n{B}{'config':8} {'recall@k':>9} {'hit@1':>7} {'MRR':>6} {'nDCG@k':>7} {'abstain':>8} {'kept':>5} "
            f"{'search':>7} {'rerank':>7}{X}"
        )
        for rep in reports:
            m = rep["metrics"]
            print(
                f"{rep['config']:8} {m['recall_at_k']:9.2f} {m['hit_at_1']:7.2f} {m['mrr']:6.2f} {m['ndcg_at_k']:7.2f}"
                f" {m['abstention']:8.2f} {m['avg_kept']:5.1f}"
                f" {m['embed_ms'] + m['search_ms']:6d}ms {m['rerank_ms']:6d}ms"
            )
        final = reports[-1]
        print(f"\n{B}Misses in '{final['config']}'{X}")
        for r in final["cases"]:
            if r["answerable"] and r["rank"] is None:
                print(
                    f"   {R}✗ {r['id']}{X} {D}kept {r['kept']}; top: {' | '.join(r['top']) or '-'}{X}"
                )
            elif not r["answerable"] and r["kept"]:
                print(
                    f"   {Y}✗ {r['id']} (unanswerable, kept {r['kept']}){X} {D}top: {' | '.join(r['top'])}{X}"
                )

        answers = None
        if args.answers:
            print(f"\n{B}End-to-end answers{X}")
            answers = answer_eval(client, idp, cases, relevant)
            print(
                "   answered with a cited, verified answer:"
                f" {answers['answered_with_cited_answer']}/{answers['answerable']}"
                f" · correct refusals: {answers['refused_correctly']}/{answers['unanswerable']}"
                f" · sentences verified {answers['verified']}, removed {answers['removed']}"
            )

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(
        json.dumps(
            {"set": args.set, "reports": reports, "answers": answers, "plans": plans}, indent=2
        )
    )
    m = final["metrics"]
    below = [k for k in ("recall_at_k", "mrr", "abstention") if m[k] < floors[k]]
    if below:
        print(
            f"\n{R}below floor: {', '.join(f'{k} {m[k]:.2f} < {floors[k]}' for k in below)}{X}  {D}({out}){X}"
        )
        return 1
    print(f"\n{G}all floors met{X}  {D}({out}){X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
