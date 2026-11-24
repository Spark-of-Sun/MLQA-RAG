"""Fetch the real public corpus and write corpus/manifest.toml (doc 19.1 R1 and R3, Appendix B).

Every item records its source URL, licence, retrieval date and SHA-256. The data directory is
git-ignored; the manifest is committed, so a fixture can always be re-fetched and re-verified.
The loader fails on any hash mismatch or missing licence. English-language documents only (v1).

Usage:  python corpus/fetchers.py            restore the manifest's documents; verify every SHA-256
        python corpus/fetchers.py --refresh  re-select from live sources and REWRITE the manifest
                                             (a manifest change is reviewed like code)
        python corpus/fetchers.py --verify   re-check hashes of what is already on disk
        python corpus/fetchers.py --quotas   report the manifest against the Appendix B minimums

Optional keys for the selection step only (restore never needs them):
  GOVINFO_API_KEY, REGULATIONS_GOV_API_KEY  api.data.gov keys; DEMO_KEY is used when unset
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
import tomllib
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MANIFEST = ROOT / "manifest.toml"
UA = "lmqa-corpus-fetcher/0.2 (contact: admin@onekami.site)"
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
ALLOWED_USE = ("commercial", "internal_eval_only", "excluded")
EXTENSIONS = {"html": "htm", "jats": "xml", "spl": "xml"}
PUBLIC_DOMAIN = "US government work (public domain)"
# Appendix B minimums (G0.8). Scanned and long documents count across both domains.
QUOTAS = {
    "legal": 150,
    "medical": 150,
    "scanned_multipage_pdf": 30,
    "long_100_pages": 10,
    "jats": 5,
    "spl": 20,
    "docx": 20,
}


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


def data_path(item: dict[str, Any]) -> Path:
    return DATA / f"{item['id']}.{EXTENSIONS.get(item['format'], item['format'])}"


def _get(client: httpx.Client, url: str, **kw: Any) -> httpx.Response:
    for attempt in range(4):
        response = client.get(url, follow_redirects=True, timeout=120, **kw)
        if response.status_code < 500 and response.status_code != 429:
            break
        time.sleep(2**attempt)  # 1s, 2s, 4s, 8s
    response.raise_for_status()
    time.sleep(0.2)  # polite to public servers (EDGAR allows 10 requests per second)
    return response


def pdf_info(body: bytes) -> tuple[int, bool]:
    """Page count, and whether the first pages are page images (a scan), read from the PDF itself."""
    try:
        reader = PdfReader(io.BytesIO(body))
        pages = len(reader.pages)
    except Exception:
        return 0, False
    imaged = 0
    sample = reader.pages[: min(3, pages)]
    for page in sample:
        try:
            xobjects = page.get("/Resources", {}).get("/XObject") or {}
            xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
            if any(xobjects[k].get_object().get("/Subtype") == "/Image" for k in xobjects):
                imaged += 1
        except Exception:  # noqa: S112 - a malformed page counts as not imaged
            continue
    return pages, bool(sample) and imaged == len(sample)


def is_docx(body: bytes) -> bool:
    try:
        return "word/document.xml" in zipfile.ZipFile(io.BytesIO(body)).namelist()
    except zipfile.BadZipFile:
        return False


def _item(content: bytes, **meta: Any) -> Item:
    DATA.mkdir(exist_ok=True)
    item = Item(
        sha256=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
        **meta,
    )
    data_path(asdict(item)).write_bytes(content)
    return item


# ---------------------------------------------------------------------------------------- legal


def edgar_contracts(client: httpx.Client, count: int = 90) -> list[Item]:
    """Material-contract exhibits (EX-10.x) from public SEC filings, across several half-years."""
    items: list[Item] = []
    seen: set[str] = set()
    windows = [
        ("2024-01-01", "2024-06-30"),
        ("2023-07-01", "2023-12-31"),
        ("2023-01-01", "2023-06-30"),
    ]
    for start, end in windows:
        for offset in (0, 100):
            search = _get(
                client,
                "https://efts.sec.gov/LATEST/search-index",
                headers={"Accept-Encoding": "gzip"},
                params={
                    "q": '"agreement"',
                    "forms": "8-K",
                    "dateRange": "custom",
                    "startdt": start,
                    "enddt": end,
                    "from": offset,
                },
            ).json()
            for hit in search["hits"]["hits"]:
                source = hit["_source"]
                if not str(source.get("file_type", "")).startswith("EX-10"):
                    continue
                adsh, filename = hit["_id"].split(":")
                if not filename.lower().endswith((".htm", ".html")):
                    continue
                item_id = f"edgar-{adsh}-{Path(filename).stem}"[:60]
                if item_id in seen:
                    continue
                seen.add(item_id)
                cik = int(source["ciks"][0])
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{filename}"
                body = _get(client, url).content
                if len(body) < 20_000:  # skip tiny exhibits; we want real multi-section contracts
                    continue
                name = source["display_names"][0].split("(")[0].strip()
                items.append(
                    _item(
                        body,
                        id=item_id,
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
                    return items
    return items


def scotus_opinion(client: httpx.Client) -> list[Item]:
    """A real born-digital PDF court opinion (US government work, public domain)."""
    url = "https://www.supremecourt.gov/opinions/23pdf/23-939_e2pg.pdf"
    body = _get(client, url).content
    pages, scanned = pdf_info(body)
    return [
        _item(
            body,
            id="scotus-23-939",
            title="Supreme Court of the United States, No. 23-939",
            source_url=url,
            license=PUBLIC_DOMAIN,
            format="pdf",
            domain="legal",
            kind="court_opinion",
            pages=pages,
            scanned=scanned,
            allowed_use="commercial",
            notes="born-digital PDF",
        )
    ]


ECFR_PARTS = [
    (45, 160), (45, 162), (45, 164), (45, 46), (45, 170), (45, 171), (42, 2), (42, 482),
    (42, 483), (21, 11), (21, 50), (21, 56), (21, 312), (21, 314), (21, 801), (21, 803),
    (21, 820), (16, 312), (16, 314), (12, 1026),
]  # fmt: skip


def ecfr_parts(client: httpx.Client) -> list[Item]:
    """CFR parts (HIPAA, human-subjects, FDA, privacy) as structured eCFR XML with section numbers."""
    items: list[Item] = []
    for title, part in ECFR_PARTS:
        url = f"https://www.ecfr.gov/api/versioner/v1/full/2024-12-31/title-{title}.xml?part={part}"
        try:
            body = _get(client, url, headers={"Accept-Encoding": "gzip"}).content
        except httpx.HTTPError:
            continue
        if len(body) < 5_000 or b'TYPE="SECTION"' not in body:
            continue
        items.append(
            _item(
                body,
                id=f"ecfr-{title}-cfr-{part}",
                title=f"{title} CFR Part {part}",
                source_url=url,
                license=PUBLIC_DOMAIN,
                format="xml",
                domain="legal",
                kind="regulation",
                pages=0,
                scanned=False,
                allowed_use="commercial",
                notes="eCFR point-in-time XML (2024-12-31); structured sections",
            )
        )
    return items


PUBLIC_LAWS = [
    ("111publ148", "Patient Protection and Affordable Care Act"),
    ("104publ191", "Health Insurance Portability and Accountability Act of 1996"),
    ("111publ5", "American Recovery and Reinvestment Act of 2009 (incl. HITECH Act)"),
    ("114publ255", "21st Century Cures Act"),
    ("110publ85", "Food and Drug Administration Amendments Act of 2007"),
    ("112publ144", "Food and Drug Administration Safety and Innovation Act"),
    ("111publ203", "Dodd-Frank Wall Street Reform and Consumer Protection Act"),
    ("116publ136", "Coronavirus Aid, Relief, and Economic Security Act"),
    ("117publ169", "Inflation Reduction Act of 2022"),
    ("115publ97", "Tax Cuts and Jobs Act (Public Law 115-97)"),
    ("117publ58", "Infrastructure Investment and Jobs Act"),
    ("107publ204", "Sarbanes-Oxley Act of 2002"),
    ("108publ173", "Medicare Prescription Drug, Improvement, and Modernization Act of 2003"),
]


def public_laws(client: httpx.Client) -> list[Item]:
    """Long born-digital statute PDFs from govinfo (PLAW collection); many run past 100 pages."""
    items: list[Item] = []
    for package, title in PUBLIC_LAWS:
        url = f"https://www.govinfo.gov/content/pkg/PLAW-{package}/pdf/PLAW-{package}.pdf"
        try:
            body = _get(client, url).content
        except httpx.HTTPError:
            continue
        if not body.startswith(b"%PDF"):
            continue
        pages, scanned = pdf_info(body)
        items.append(
            _item(
                body,
                id=f"plaw-{package}",
                title=title,
                source_url=url,
                license=PUBLIC_DOMAIN,
                format="pdf",
                domain="legal",
                kind="statute",
                pages=pages,
                scanned=scanned,
                allowed_use="commercial",
                notes="govinfo public law PDF",
            )
        )
    return items


def statutes_at_large_scans(client: httpx.Client, count: int = 35) -> list[Item]:
    """Multi-page laws from digitized print volumes of the Statutes at Large (page-image PDFs)."""
    key = os.environ.get("GOVINFO_API_KEY", "DEMO_KEY")
    items: list[Item] = []
    for volume in (65, 66, 67, 68, 69, 70):
        try:
            listing = _get(
                client,
                f"https://api.govinfo.gov/packages/STATUTE-{volume}/granules",
                params={"offsetMark": "*", "pageSize": 400, "api_key": key},
            ).json()
        except httpx.HTTPError:
            continue
        for granule in listing.get("granules", []):
            if granule.get("granuleClass") != "PUBLICLAW":
                continue
            gid = granule["granuleId"]
            url = f"https://www.govinfo.gov/content/pkg/STATUTE-{volume}/pdf/{gid}.pdf"
            try:
                body = _get(client, url).content
            except httpx.HTTPError:
                continue
            if not body.startswith(b"%PDF"):
                continue
            pages, scanned = pdf_info(body)
            if pages < 3 or not scanned:
                continue
            items.append(
                _item(
                    body,
                    id=f"statute-{gid[len('STATUTE-') :]}".lower(),
                    title=f"{volume} Stat.: {str(granule.get('title', gid))[:180]}",
                    source_url=url,
                    license=PUBLIC_DOMAIN,
                    format="pdf",
                    domain="legal",
                    kind="statute",
                    pages=pages,
                    scanned=True,
                    allowed_use="commercial",
                    notes="digitized print volume: page images with an OCR layer",
                )
            )
            if len(items) == count:
                return items
    return items


# -------------------------------------------------------------------------------------- medical


def _europepmc_search(client: httpx.Client, cursor: str) -> dict[str, Any]:
    query = 'OPEN_ACCESS:y AND (LICENSE:"cc by" OR LICENSE:"cc0") AND "case report" AND HAS_FT:y'
    return _get(
        client,
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            "query": f'{query} AND TITLE:"case report" AND LANG:eng',
            "format": "json",
            "pageSize": 100,
            "resultType": "core",
            "cursorMark": cursor,
        },
    ).json()


def europepmc_case_reports(client: httpx.Client, jats: int = 65, pdfs: int = 20) -> list[Item]:  # noqa: C901 - one paged walk feeds both formats
    """Open-access case reports with CC BY or CC0 licences: JATS XML, plus the article PDF for some."""
    items: list[Item] = []
    have_jats = have_pdf = 0
    cursor = "*"
    for _ in range(6):
        result = _europepmc_search(client, cursor)
        for record in result["resultList"]["result"]:
            pmcid, licence = record.get("pmcid"), record.get("license")
            if not pmcid or str(licence).lower() not in ("cc by", "cc0"):
                continue
            title = str(record.get("title", pmcid))[:200]
            meta = {"domain": "medical", "kind": "case_report", "allowed_use": "commercial"}
            if have_jats < jats:
                url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
                try:
                    body = _get(client, url).content
                except httpx.HTTPError:
                    continue
                if len(body) < 15_000 or b"<sec" not in body:
                    continue
                items.append(
                    _item(
                        body, id=f"pmc-{pmcid}", title=title, source_url=url, license=str(licence),
                        format="jats", pages=0, scanned=False,
                        notes="open-access case report (JATS XML)", **meta,
                    )
                )  # fmt: skip
                have_jats += 1
            elif have_pdf < pdfs:
                url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                try:
                    body = _get(client, url).content
                except httpx.HTTPError:
                    continue
                if not body.startswith(b"%PDF"):
                    continue
                pages, scanned = pdf_info(body)
                items.append(
                    _item(
                        body, id=f"pmcpdf-{pmcid}", title=title, source_url=url,
                        license=str(licence), format="pdf", pages=pages, scanned=scanned,
                        notes="open-access case report (publisher PDF)", **meta,
                    )
                )  # fmt: skip
                have_pdf += 1
            if have_jats >= jats and have_pdf >= pdfs:
                return items
        cursor = result.get("nextCursorMark") or ""
        if not cursor:
            break
    return items


def dailymed_labels(client: httpx.Client, count: int = 70) -> list[Item]:
    """Prescription drug labels as SPL XML (FDA DailyMed)."""
    items: list[Item] = []
    for page in range(1, 6):
        listing = _get(
            client,
            "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json",
            params={"pagesize": 40, "page": page},
        ).json()
        for entry in listing["data"]:
            url = f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{entry['setid']}.xml"
            try:
                body = _get(client, url).content
            except httpx.HTTPError:
                continue
            if len(body) < 30_000:
                continue
            items.append(
                _item(
                    body,
                    id=f"dailymed-{entry['setid'][:8]}",
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
                return items
    return items


def regulations_gov_docx(client: httpx.Client, count: int = 20, budget: int = 45) -> list[Item]:
    """Agency-authored DOCX documents (FDA, CMS) posted to regulations.gov; never public comments."""
    key = os.environ.get("REGULATIONS_GOV_API_KEY", "DEMO_KEY")
    items: list[Item] = []
    calls = 0
    for agency in ("FDA", "CMS"):
        try:
            listing = _get(
                client,
                "https://api.regulations.gov/v4/documents",
                params={
                    "filter[agencyId]": agency,
                    "filter[documentType]": "Supporting & Related Material",
                    "page[size]": 100,
                    "sort": "-postedDate",
                    "api_key": key,
                },
            ).json()
        except httpx.HTTPError:
            continue
        calls += 1
        for doc in listing.get("data", []):
            if calls >= budget or len(items) == count:
                return items
            try:
                detail = _get(
                    client,
                    f"https://api.regulations.gov/v4/documents/{doc['id']}",
                    params={"include": "attachments", "api_key": key},
                ).json()
            except httpx.HTTPError:
                continue
            calls += 1
            formats = list(detail["data"]["attributes"].get("fileFormats") or [])
            for attachment in detail.get("included", []):
                formats.extend(attachment["attributes"].get("fileFormats") or [])
            urls = [f["fileUrl"] for f in formats if str(f.get("format")).lower() == "docx"]
            if not urls:
                continue
            body = _get(client, urls[0]).content
            if not is_docx(body):
                continue
            items.append(
                _item(
                    body,
                    id=f"regsgov-{doc['id']}".lower()[:60],
                    title=str(doc["attributes"].get("title") or doc["id"])[:200],
                    source_url=urls[0],
                    license=f"{PUBLIC_DOMAIN}; agency-posted, docket {doc['attributes'].get('docketId')}",
                    format="docx",
                    domain="medical",
                    kind="agency_document",
                    pages=0,
                    scanned=False,
                    allowed_use="commercial",
                    notes=f"{agency} supporting material on regulations.gov",
                )
            )
    return items


# NIH institutes publish clinical-trial templates as DOCX. Both reuse policies were read on 2026-11-23:
# cancer.gov/policies/copyright-reuse ("all text ... is free of copyright") and
# nidcr.nih.gov/about-us/web-policies ("within the public domain ... may be freely ... reproduced").
NIH_DOCX_PAGES = (
    (
        "https://dctd.cancer.gov/research/ctep-trials/trial-development",
        "nci",
        "US government work (NCI); text free of copyright per cancer.gov/policies/copyright-reuse",
    ),
    (
        "https://www.nidcr.nih.gov/research/conducting-nidcr-clinical-research/tools-templates",
        "nidcr",
        "US government work (NIDCR); public domain per nidcr.nih.gov/about-us/web-policies",
    ),
    (
        "https://www.nidcr.nih.gov/research/conducting-nidcr-clinical-research/nidcr-oversight-related-templates",
        "nidcr",
        "US government work (NIDCR); public domain per nidcr.nih.gov/about-us/web-policies",
    ),
)


def nih_docx_templates(client: httpx.Client, count: int = 30) -> list[Item]:
    """Clinical-trial protocol, consent and oversight templates (DOCX) from NCI CTEP and NIDCR."""
    items: list[Item] = []
    seen: set[str] = set()
    for page, institute, licence in NIH_DOCX_PAGES:
        html = _get(client, page).text
        for href in re.findall(r'href="([^"]+\.docx)"', html, flags=re.IGNORECASE):
            url = urljoin(page, href)
            if url in seen:
                continue
            seen.add(url)
            try:
                body = _get(client, url).content
            except httpx.HTTPError:
                continue
            if not is_docx(body):
                continue
            stem = Path(unquote(urlparse(url).path)).stem
            slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
            agreement = "agreement" in slug
            items.append(
                _item(
                    body,
                    id=f"{institute}-{slug}"[:60],
                    title=f"{institute.upper()}: {stem.replace('-', ' ')}"[:200],
                    source_url=url,
                    license=licence,
                    format="docx",
                    domain="legal" if agreement else "medical",
                    kind="contract_template" if agreement else "clinical_trial_template",
                    pages=0,
                    scanned=False,
                    allowed_use="commercial",
                    notes=f"agency-authored template linked from {page}",
                )
            )
            if len(items) == count:
                return items
    return items


SOURCES: list[Callable[[httpx.Client], list[Item]]] = [
    edgar_contracts,
    scotus_opinion,
    ecfr_parts,
    public_laws,
    statutes_at_large_scans,
    europepmc_case_reports,
    dailymed_labels,
    regulations_gov_docx,
    nih_docx_templates,
]


# ------------------------------------------------------------------------------------- manifest


def write_manifest(items: list[Item]) -> None:
    lines = ["# Generated by corpus/fetchers.py --refresh. A refresh is a reviewed change.", ""]
    for item in items:
        lines.append("[[item]]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in asdict(item).items())
        lines.append("")
    MANIFEST.write_text("\n".join(lines), encoding="utf-8")


def load_manifest() -> list[dict[str, Any]]:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8")).get("item", [])


def problems_in(item: dict[str, Any]) -> list[str]:
    missing = [k for k in REQUIRED if item.get(k) in (None, "")]
    if missing:
        return [f"{item.get('id')}: missing {missing}"]
    if item["allowed_use"] not in ALLOWED_USE:
        return [f"{item['id']}: allowed_use must be one of {ALLOWED_USE}"]
    return []


def quotas(items: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Actual against minimum for each Appendix B quota."""
    shipped = [i for i in items if i["allowed_use"] != "excluded"]
    domains = Counter(i["domain"] for i in shipped)
    formats = Counter(i["format"] for i in shipped)
    actual = {
        "legal": domains["legal"],
        "medical": domains["medical"],
        "scanned_multipage_pdf": sum(
            1 for i in shipped if i["format"] == "pdf" and i["scanned"] and i["pages"] > 1
        ),
        "long_100_pages": sum(1 for i in shipped if i["pages"] >= 100),
        "jats": formats["jats"],
        "spl": formats["spl"],
        "docx": formats["docx"],
    }
    return {name: (actual[name], minimum) for name, minimum in QUOTAS.items()}


def verify() -> list[str]:
    """Return problems: missing fields, missing files or hash mismatches."""
    problems: list[str] = []
    for item in load_manifest():
        found = problems_in(item)
        if found:
            problems.extend(found)
            continue
        path = data_path(item)
        if not path.is_file():
            problems.append(f"{item['id']}: file missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            problems.append(f"{item['id']}: sha256 mismatch")
    return problems


def restore() -> list[str]:
    """Download exactly the manifest's documents; verify each against its recorded SHA-256."""
    problems: list[str] = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for item in load_manifest():
            found = problems_in(item)
            if found:
                problems.extend(found)
                continue
            path = data_path(item)
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
                continue
            try:
                body = _get(client, item["source_url"], headers={"Accept-Encoding": "gzip"}).content
            except httpx.HTTPError as exc:
                problems.append(f"{item['id']}: download failed ({type(exc).__name__})")
                continue
            if hashlib.sha256(body).hexdigest() != item["sha256"]:
                problems.append(
                    f"{item['id']}: the upstream document changed (hash differs); review it and run --refresh"
                )
                continue
            DATA.mkdir(exist_ok=True)
            path.write_bytes(body)
    return problems


def refresh() -> list[Item]:
    items: list[Item] = []
    seen: set[str] = set()
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for source in SOURCES:
            try:
                found = source(client)
            except Exception as exc:
                print(f"{source.__name__}: stopped ({type(exc).__name__}: {exc})", flush=True)
                continue
            fresh = [i for i in found if i.id not in seen]
            seen.update(i.id for i in fresh)
            items.extend(fresh)
            print(f"{source.__name__}: {len(fresh)} item(s)", flush=True)
    return items


def print_quotas(items: list[dict[str, Any]]) -> bool:
    met = True
    for name, (actual, minimum) in quotas(items).items():
        met &= actual >= minimum
        print(f"{name:24} {actual:>4} / {minimum:<4} {'ok' if actual >= minimum else 'SHORT'}")
    return met


def main() -> int:
    if "--verify" in sys.argv:
        problems = verify()
        print("\n".join(problems) or "corpus verified")
        return 1 if problems else 0
    if "--quotas" in sys.argv:
        return 0 if print_quotas(load_manifest()) else 1
    if "--refresh" not in sys.argv:
        problems = restore()
        print("\n".join(problems) or "corpus restored and verified")
        return 1 if problems else 0
    items = refresh()
    write_manifest(items)
    print_quotas([asdict(i) for i in items])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
