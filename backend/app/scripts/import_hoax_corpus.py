"""Import datasets/indonesia_hoax_news/ into a DRAFT dataset_samples corpus
(04_AI_and_ML/04_Datasets_and_Operator_Feedback.md; audit_answers.md §18/§22
step 4 — "real data sitting unused").

Usage: `python -m app.scripts.import_hoax_corpus`

Legit outlets (antaranews/detik/kompas, label 0) map directly to
NOT_A_THREAT — a fact of which file a row came from, not a guess.
TurnBackHoax rows (tbh_cleaned_v3.csv, label 1) are hoaxes, but the source
data is only binary — it doesn't say *which* of the five hoax classes a
given article is. Splitting them requires the "manual/LLM-assisted
relabeling" audit_answers.md §18 calls for; this script does the cheap,
deterministic, auditable half of that — keyword-based heuristic
classification — and stops there. It lands the whole corpus as a single
DRAFT dataset, immediately queryable, but never calls VALIDATE itself:
this codebase's human-gated design principle
(08_Continuous_Improvement_Loop.md forbids auto-promotion) means a
heuristically-labeled ~24k-row corpus needs an operator to look at
`label_counts`, spot-check a sample, and VALIDATE deliberately before any
training job can consume it.

Idempotent by (dataset name, version), same convention as
`seed_dataset_samples.py`: a dataset already at VALIDATED/ARCHIVED is left
untouched; one stuck in DRAFT from a previous partial run is reported, not
auto-repaired.
"""

import asyncio
import csv
import logging
import os
import re
from collections.abc import Iterator
from pathlib import Path

import asyncpg

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.datasets import _PHONE_PATTERN, create_dataset

logger = logging.getLogger("app.scripts.import_hoax_corpus")

_DATASET_NAME = "indonesia-hoax-corpus-import"
_DATASET_VERSION = 1
# `parents[3]` only lands on the repo root in local dev, where this file sits
# at <repo>/backend/app/scripts/. Inside the container the same source tree
# is copied to /app/app/scripts/ (backend/ is the Dockerfile build context,
# so one path segment is missing) — HOAX_CORPUS_DIR overrides for that case,
# set in docker-compose.yml alongside the ./datasets bind mount, since
# datasets/ is never baked into the image.
_CORPUS_DIR = (
    Path(os.environ["HOAX_CORPUS_DIR"])
    if "HOAX_CORPUS_DIR" in os.environ
    else Path(__file__).resolve().parents[3] / "datasets" / "indonesia_hoax_news"
)

_LEGIT_FILES = ("antaranews_cleaned_v3.csv", "detik_cleaned_v3.csv", "kompas_cleaned_v3.csv")
_HOAX_FILE = "tbh_cleaned_v3.csv"

# Ordered most-specific-first: a row matching an earlier bucket never falls
# through to a later, vaguer one. GENERAL_NEWS is the taxonomy's own
# catch-all for hoax content that doesn't fit a more specific class — same
# reasoning `app/pipeline/threat_categories.py` uses for that enum member.
_HOAX_KEYWORD_BUCKETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FILE_APK", re.compile(r"\.apk\b|instal(?:l|asi)?\s+aplikasi|unduh\s+aplikasi", re.IGNORECASE)),
    (
        "PHISHING_LINK",
        re.compile(
            r"https?://|bit\.ly|tinyurl|klik\s+link|klik\s+tautan|verifikasi\s+akun|verifikasi\s+data",
            re.IGNORECASE,
        ),
    ),
    (
        "FINANCIAL_FRAUD",
        re.compile(
            r"transfer|rekening|\botp\b|\bpin\b|\bbank\b|undian|hadiah|bansos|bantuan\s+tunai|pinjaman|investasi",
            re.IGNORECASE,
        ),
    ),
    (
        "HEALTH_HOAX",
        re.compile(
            r"\bobat\b|sembuh|penyakit|vaksin|dokter|kanker|\bvirus\b|covid|rumah\s+sakit|kesehatan",
            re.IGNORECASE,
        ),
    ),
)
_DEFAULT_HOAX_LABEL = "GENERAL_NEWS"


def classify_hoax_text(text: str) -> str:
    """Deterministic keyword heuristic — see module docstring for why this
    stops short of a real relabel. Never raises; unmatched text lands on
    GENERAL_NEWS, the taxonomy's catch-all.
    """
    for label, pattern in _HOAX_KEYWORD_BUCKETS:
        if pattern.search(text):
            return label
    return _DEFAULT_HOAX_LABEL


def _read_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def collect_samples() -> list[tuple[str, str]]:
    """(text, label) pairs, deduplicated by text — VALIDATE rejects exact
    duplicates — with first-seen order preserved. Rows containing a raw
    Indonesian phone number (same `_PHONE_PATTERN` VALIDATE checks) are
    dropped outright rather than redacted: TurnBackHoax articles sometimes
    quote a scammer's number verbatim, and editing the text to pass the
    check would be a worse trade than losing the ~1% of rows affected.
    """
    seen: set[str] = set()
    samples: list[tuple[str, str]] = []

    def _add(text: str | None, label: str) -> None:
        if not text:
            return
        cleaned = text.strip()
        if not cleaned or cleaned in seen or _PHONE_PATTERN.search(cleaned):
            return
        seen.add(cleaned)
        samples.append((cleaned, label))

    for filename in _LEGIT_FILES:
        for row in _read_rows(_CORPUS_DIR / filename):
            _add(row.get("narasi"), "NOT_A_THREAT")

    for row in _read_rows(_CORPUS_DIR / _HOAX_FILE):
        narasi = row.get("narasi")
        if not narasi:
            continue
        _add(narasi, classify_hoax_text(narasi))

    return samples


async def _get_seed_operator(conn: asyncpg.Connection) -> str:
    operator_id = await conn.fetchval("SELECT id FROM operators ORDER BY created_at LIMIT 1")
    if operator_id is None:
        raise RuntimeError("no operator account exists — run `app.scripts.create_operator` first")
    return str(operator_id)


async def run() -> dict[str, object]:
    settings = get_settings()
    samples = collect_samples()

    conn = await asyncpg.connect(settings.database_url, timeout=30)
    try:
        existing = await conn.fetchrow(
            "SELECT id, status::text AS status FROM datasets WHERE name = $1 AND version = $2",
            _DATASET_NAME,
            _DATASET_VERSION,
        )
        if existing is not None:
            if existing["status"] in ("VALIDATED", "ARCHIVED"):
                logger.info("dataset already %s, skipping import", existing["status"])
                return {"dataset_id": str(existing["id"]), "status": existing["status"], "imported": 0}
            raise RuntimeError(
                f"dataset '{_DATASET_NAME}' v{_DATASET_VERSION} exists but is {existing['status']} — "
                "left over from a partial run, clean it up manually before re-importing"
            )

        operator_id = await _get_seed_operator(conn)
        dataset = await create_dataset(
            _DATASET_NAME,
            _DATASET_VERSION,
            "IMPORTED",
            (
                f"Imported from datasets/indonesia_hoax_news/ ({len(samples)} deduplicated rows). "
                "Hoax rows are keyword-heuristic labeled into the five threat classes — "
                "review label_counts and VALIDATE deliberately before use in training."
            ),
            operator_id,
            settings=settings,
        )
        dataset_id = dataset["id"]

        await conn.executemany(
            "INSERT INTO dataset_samples (dataset_id, text, label, added_by) VALUES ($1, $2, $3, $4)",
            [(dataset_id, text, label, operator_id) for text, label in samples],
        )
    finally:
        await conn.close()

    label_counts: dict[str, int] = {}
    for _, label in samples:
        label_counts[label] = label_counts.get(label, 0) + 1

    return {"dataset_id": dataset_id, "status": "DRAFT", "imported": len(samples), "label_counts": label_counts}


def main() -> None:
    configure_logging(get_settings().log_level)
    logger.info("hoax corpus import finished", extra=asyncio.run(run()))


if __name__ == "__main__":
    main()
