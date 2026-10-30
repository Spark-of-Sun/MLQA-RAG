"""Fetch the real public corpus and write corpus/manifest.toml (doc 19.1 R1 and R3, Appendix B).

Every item records its source URL, licence, retrieval date and SHA-256. The data directory is
git-ignored; the manifest is committed, so a fixture can always be re-fetched and re-verified.
The loader fails on any hash mismatch or missing licence. English-language documents only (v1).

Usage:  python corpus/fetchers.py            restore the manifest's documents; verify every SHA-256
        python corpus/fetchers.py --refresh  re-select from live sources and REWRITE the manifest
                                             (a manifest change is reviewed like code)
        python corpus/fetchers.py --verify   re-check hashes of what is already on disk
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MANIFEST = ROOT / "manifest.toml"
UA = "lmqa-corpus-fetcher/0.1 (contact: admin@onekami.site)"
REQUIRED = (
    "id",
    "title",
    "source_url",
    "license",
    "retrieved_at",
    "sha256",
    "bytes",
    "format",
    "domain",
    "kind",
    "allowed_use",
)
EXTENSIONS = {"html": "htm", "jats": "xml", "spl": "xml"}


@dataclass
class Item:
    id: str
    title: str
    source_url: str
    license: str
    retrieved_at: str
    sha256: str
    bytes: int
    format: str
    domain: str
    kind: str
    pages: int
    scanned: bool
    allowed_use: str
    notes: str


def _get(client: httpx.Client, url: str, **kw: Any) -> httpx.Response:
    response = client.get(url, follow_redirects=True, timeout=60, **kw)
    response.raise_for_status()
    time.sleep(0.2)  # polite to public servers (EDGAR allows 10 requests per second)
    return response


def _item(content: bytes, **meta: Any) -> Item:
    DATA.mkdir(exist_ok=True)
    ext = meta.pop("ext")
    (DATA / f"{meta['id']}.{ext}").write_bytes(content)
    return Item(
        sha256=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
        **meta,
    )


def edgar_contracts(client: httpx.Client, count: int = 4) -> list[Item]:
    """Material-contract exhibits (EX-10.x) from public SEC filings."""
    search = _get(
        client,
        "https://efts.sec.gov/LATEST/search-index",
        params={
            "q": '"agreement"',
            "forms": "8-K",
            "dateRange": "custom",
            "startdt": "2024-01-01",
            "enddt": "2024-06-30",
        },
    ).json()
    items: list[Item] = []
    for hit in search["hits"]["hits"]:
        source = hit["_source"]
        if not str(source.get("file_type", "")).startswith("EX-10"):
            continue
        adsh, filename = hit["_id"].split(":")
        cik = int(source["ciks"][0])
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{filename}"
        body = _get(client, url).content
        if len(body) < 20_000:  # skip tiny exhibits; we want real multi-section contracts
            continue
        name = source["display_names"][0].split("(")[0].strip()
        items.append(
            _item(
                body,
                id=f"edgar-{adsh}-{Path(filename).stem}"[:60],
                ext="htm",
                title=f"{name}: {source['file_type']}",
                source_url=url,
                license="SEC EDGAR public filing (no copyright restriction asserted; verify)",
                format="html",
                domain="legal",
                kind="contract",
                pages=0,
                scanned=False,
                allowed_use="commercial",
                notes="material contract exhibit",
            )
        )
        if len(items) == count:
            break
    return items


def scotus_opinion(client: httpx.Client) -> list[Item]:
    """A real born-digital PDF court opinion (US government work, public domain)."""
    url = "https://www.supremecourt.gov/opinions/23pdf/23-939_e2pg.pdf"
    body = _get(client, url).content
    return [
        _item(
            body,
            id="scotus-23-939",
            ext="pdf",
            title="Supreme Court of the United States, No. 23-939",
            source_url=url,
            license="US government work (public domain)",
            format="pdf",
            domain="legal",
            kind="court_opinion",
            pages=0,
            scanned=False,
            allowed_use="commercial",
            notes="born-digital PDF",
        )
    ]


def ecfr_hipaa(client: httpx.Client) -> list[Item]:
    """45 CFR Part 164 (HIPAA Security and Privacy Rules), structured XML with section numbering."""
    url = "https://www.ecfr.gov/api/versioner/v1/full/2024-12-31/title-45.xml?part=164"
    body = _get(client, url, headers={"Accept-Encoding": "gzip"}).content
    return [
        _item(
            body,
            id="ecfr-45-cfr-164",
            ext="xml",
            title="45 CFR Part 164 (HIPAA Security and Privacy)",
            source_url=url,
            license="US government work (public domain)",
            format="xml",
            domain="legal",
            kind="regulation",
            pages=0,
            scanned=False,
            allowed_use="commercial",
            notes="structured sections; regulatory text",
        )
    ]


def europepmc_case_reports(client: httpx.Client, count: int = 3) -> list[Item]:
    """Open-access case reports with permissive licences, as JATS XML."""
    query = 'OPEN_ACCESS:y AND (LICENSE:"cc by" OR LICENSE:"cc0") AND "case report" AND HAS_FT:y'
    result = _get(
        client,
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "pageSize": 25, "resultType": "core"},
    ).json()
    items: list[Item] = []
    for record in result["resultList"]["result"]:
        pmcid, licence = record.get("pmcid"), record.get("license")
        if not pmcid or not licence:
            continue
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        body = _get(client, url).content
        if len(body) < 15_000 or b"<sec" not in body:
            continue
        items.append(
            _item(
                body,
                id=f"pmc-{pmcid}",
                ext="xml",
                title=str(record.get("title", pmcid))[:200],
                source_url=url,
                license=str(licence),
                format="jats",
                domain="medical",
                kind="case_report",
                pages=0,
                scanned=False,
                allowed_use="commercial",
                notes="open-access case report (JATS XML)",
            )
        )
        if len(items) == count:
            break
    return items


def dailymed_labels(client: httpx.Client, count: int = 3) -> list[Item]:
    """Prescription drug labels as SPL XML (FDA DailyMed)."""
    listing = _get(
        client,
        "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json",
        params={"pagesize": 40, "page": 1},
    ).json()
    items: list[Item] = []
    for entry in listing["data"]:
        url = f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{entry['setid']}.xml"
        body = _get(client, url).content
        if len(body) < 30_000:
            continue
        items.append(
            _item(
                body,
                id=f"dailymed-{entry['setid'][:8]}",
                ext="xml",
                title=str(entry["title"])[:200],
                source_url=url,
                license="US government work (FDA DailyMed; public)",
                format="spl",
                domain="medical",
                kind="drug_label",
                pages=0,
                scanned=False,
                allowed_use="commercial",
                notes="SPL XML with LOINC section codes",
            )
        )
        if len(items) == count:
            break
    return items


def write_manifest(items: list[Item]) -> None:
    lines = ["# Generated by corpus/fetchers.py. A refresh is a reviewed change.", ""]
    for item in items:
        lines.append("[[item]]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in asdict(item).items())
        lines.append("")
    MANIFEST.write_text("\n".join(lines), encoding="utf-8")


def verify() -> list[str]:
    """Return problems: missing fields, missing files or hash mismatches."""
    problems: list[str] = []
    for item in tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["item"]:
        missing = [k for k in REQUIRED if item.get(k) in (None, "")]
        if missing:
            problems.append(f"{item.get('id')}: missing {missing}")
            continue
        path = DATA / f"{item['id']}.{EXTENSIONS.get(item['format'], item['format'])}"
        if not path.is_file():
            problems.append(f"{item['id']}: file missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            problems.append(f"{item['id']}: sha256 mismatch")
    return problems


def restore() -> list[str]:
    """Download exactly the manifest's documents; verify each against its recorded SHA-256."""
    problems: list[str] = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for item in tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["item"]:
            path = DATA / f"{item['id']}.{EXTENSIONS.get(item['format'], item['format'])}"
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
                continue
            try:
                body = _get(client, item["source_url"], headers={"Accept-Encoding": "gzip"}).content
            except httpx.HTTPError as exc:
                problems.append(f"{item['id']}: download failed ({type(exc).__name__})")
                continue
            if hashlib.sha256(body).hexdigest() != item["sha256"]:
                problems.append(
                    f"{item['id']}: the upstream document changed (hash differs); "
                    "review it and run --refresh"
                )
                continue
            DATA.mkdir(exist_ok=True)
            path.write_bytes(body)
    return problems


def main() -> int:
    if "--refresh" not in sys.argv and "--verify" not in sys.argv:
        problems = restore()
        print("\n".join(problems) or "corpus restored and verified")
        return 1 if problems else 0
    if "--verify" in sys.argv:
        problems = verify()
        print("\n".join(problems) or "corpus verified")
        return 1 if problems else 0
    with httpx.Client(headers={"User-Agent": UA}) as client:
        items = [
            *edgar_contracts(client),
            *scotus_opinion(client),
            *ecfr_hipaa(client),
            *europepmc_case_reports(client),
            *dailymed_labels(client),
        ]
    write_manifest(items)
    for item in items:
        print(f"{item.domain:8} {item.kind:14} {item.bytes:>9}  {item.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
