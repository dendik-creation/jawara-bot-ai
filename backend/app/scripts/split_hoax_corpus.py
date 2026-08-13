"""Split datasets/indonesia_hoax_news/ into two independent dataset_samples
sets — train and eval — stratified per label, for 07_How_to_Run/
03_How_To_Train_AI.md §0's requirement that training and evaluation datasets
never overlap (leakage otherwise makes the accuracy number meaningless).

Usage: `python -m app.scripts.split_hoax_corpus [--eval-fraction 0.2] [--seed 42]`

Reuses `app.scripts.import_hoax_corpus.collect_samples` (same keyword-heuristic
hoax labeling) directly from the CSVs rather than depending on
`indonesia-hoax-corpus-import` having been run first — running both against
the same source files is fine, they land in separate dataset rows.

Split is stratified: each label's samples are shuffled with a fixed seed
(reproducible re-runs) and cut at `eval_fraction`, so both output datasets
carry every label that has at least one sample. A label absent from the
source corpus (see script docstring history: FILE_APK has zero hits in the
TurnBackHoax heuristic buckets) stays absent from both — this script cannot
invent samples for it; add those manually (03_How_To_Train_AI.md §1) before
training if that label matters for evaluation.

Both output datasets land as DRAFT — this script never calls VALIDATE. Same
human-gated principle as import_hoax_corpus.py: an operator reviews
label_counts and validates deliberately.

Idempotent by (dataset name, version): a dataset already at VALIDATED/ARCHIVED
is left untouched; one stuck in DRAFT from a previous partial run is
reported, not auto-repaired.
"""

import argparse
import asyncio
import logging
import random
from collections import defaultdict

import asyncpg

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.scripts.import_hoax_corpus import _get_seed_operator, collect_samples
from app.services.datasets import create_dataset

logger = logging.getLogger("app.scripts.split_hoax_corpus")

_TRAIN_NAME = "indonesia-hoax-train"
_EVAL_NAME = "indonesia-hoax-eval"
_VERSION = 1


def stratified_split(
    samples: list[tuple[str, str]], eval_fraction: float, seed: int
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    by_label: dict[str, list[str]] = defaultdict(list)
    for text, label in samples:
        by_label[label].append(text)

    rng = random.Random(seed)
    train: list[tuple[str, str]] = []
    eval_: list[tuple[str, str]] = []
    for label, texts in by_label.items():
        shuffled = texts[:]
        rng.shuffle(shuffled)
        # A single-sample label goes entirely to train — an eval-only label
        # with zero training exposure is not a meaningful split.
        cut = max(1, round(len(shuffled) * eval_fraction)) if len(shuffled) > 1 else 0
        eval_texts, train_texts = shuffled[:cut], shuffled[cut:]
        eval_.extend((t, label) for t in eval_texts)
        train.extend((t, label) for t in train_texts)
    return train, eval_


def _label_counts(rows: list[tuple[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, label in rows:
        counts[label] = counts.get(label, 0) + 1
    return counts


async def _create_and_fill(
    conn: asyncpg.Connection,
    name: str,
    version: int,
    description: str,
    operator_id: str,
    samples: list[tuple[str, str]],
    settings: object,
) -> dict[str, object]:
    existing = await conn.fetchrow(
        "SELECT id, status::text AS status FROM datasets WHERE name = $1 AND version = $2", name, version
    )
    if existing is not None:
        if existing["status"] in ("VALIDATED", "ARCHIVED"):
            logger.info("%s already %s, skipping", name, existing["status"])
            return {"dataset_id": str(existing["id"]), "status": existing["status"], "imported": 0}
        raise RuntimeError(
            f"dataset '{name}' v{version} exists but is {existing['status']} — "
            "left over from a partial run, clean it up manually before re-splitting"
        )

    dataset = await create_dataset(name, version, "IMPORTED", description, operator_id, settings=settings)
    dataset_id = dataset["id"]
    await conn.executemany(
        "INSERT INTO dataset_samples (dataset_id, text, label, added_by) VALUES ($1, $2, $3, $4)",
        [(dataset_id, text, label, operator_id) for text, label in samples],
    )
    return {"dataset_id": dataset_id, "status": "DRAFT", "imported": len(samples)}


async def run(eval_fraction: float, seed: int) -> dict[str, object]:
    settings = get_settings()
    samples = collect_samples()
    train, eval_ = stratified_split(samples, eval_fraction, seed)

    conn = await asyncpg.connect(settings.database_url, timeout=30)
    try:
        operator_id = await _get_seed_operator(conn)
        train_result = await _create_and_fill(
            conn,
            _TRAIN_NAME,
            _VERSION,
            (
                f"Stratified {1 - eval_fraction:.0%} train split of indonesia_hoax_news (seed={seed}), "
                f"disjoint from {_EVAL_NAME} v{_VERSION}. Hoax rows keyword-heuristic labeled — review "
                "label_counts and VALIDATE deliberately before use in a training job."
            ),
            operator_id,
            train,
            settings,
        )
        eval_result = await _create_and_fill(
            conn,
            _EVAL_NAME,
            _VERSION,
            (
                f"Stratified {eval_fraction:.0%} eval split of indonesia_hoax_news (seed={seed}), disjoint "
                f"from {_TRAIN_NAME} v{_VERSION}. Hoax rows keyword-heuristic labeled — review label_counts "
                "and VALIDATE deliberately before use as held-out evaluation data."
            ),
            operator_id,
            eval_,
            settings,
        )
    finally:
        await conn.close()

    return {
        "train": {**train_result, "label_counts": _label_counts(train)},
        "eval": {**eval_result, "label_counts": _label_counts(eval_)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    logger.info("hoax corpus split finished", extra=asyncio.run(run(args.eval_fraction, args.seed)))


if __name__ == "__main__":
    main()
