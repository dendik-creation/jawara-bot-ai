"""Seed the knowledge base with the documented example facts.

Usage: `python -m app.scripts.seed_facts`

Development/demo data only — these are the cases used as few-shot examples in
`04_AI_and_ML/01_LLM_System_Prompt.md`, so a freshly built stack can be
exercised end to end without waiting for real curation. Real knowledge arrives
through the operator upload path ([[03_Knowledge_Base]], Planned).

Idempotent: rows are matched on `source_url`, so re-running updates rather than
duplicating. Run `python -m app.scripts.ingest_knowledge` afterwards to embed
them into Qdrant.
"""

import asyncio
import logging

import asyncpg

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger("app.scripts.seed_facts")

SOURCES = [
    ("TurnBackHoax", "https://turnbackhoax.id", True),
    ("Kementerian Kesehatan RI", "https://kemkes.go.id", True),
    ("Kementerian Sosial RI", "https://cekbansos.kemensos.go.id", True),
    ("Patroli Siber", "https://patrolisiber.id", True),
]

FACTS = [
    {
        "source": "TurnBackHoax",
        "category": "HEALTH_HOAX",
        "title": "Klaim Daun Kitolod Menyembuhkan Katarak Tanpa Operasi",
        "claim_summary": (
            "Air rebusan atau perasan daun kitolod dapat menyembuhkan katarak dan "
            "membersihkan mata tanpa perlu operasi."
        ),
        "fact_explanation": (
            "Kementerian Kesehatan RI dan Perhimpunan Dokter Spesialis Mata Indonesia (PERDAMI) "
            "menegaskan bahwa penggunaan air ramuan daun liar pada mata berisiko tinggi "
            "menyebabkan iritasi, infeksi bakteri, hingga kebutaan permanen. Katarak hanya dapat "
            "ditangani melalui tindakan medis oleh dokter spesialis mata."
        ),
        "verdict": "HOAX",
        "source_url": "https://turnbackhoax.id/2026/01/10/hoax-kitolod-katarak/",
    },
    {
        "source": "Kementerian Kesehatan RI",
        "category": "GENERAL_NEWS",
        "title": "Program Vaksinasi Influenza Gratis di Puskesmas",
        "claim_summary": (
            "Puskesmas membuka program vaksinasi influenza gratis bagi lansia dan kelompok rentan."
        ),
        "fact_explanation": (
            "Kementerian Kesehatan dan Dinas Kesehatan setempat menyelenggarakan vaksinasi "
            "influenza gratis bagi lansia dan kelompok rentan di Puskesmas terdekat. Peserta "
            "cukup membawa KTP saat berkunjung."
        ),
        "verdict": "FACT",
        "source_url": "https://kemkes.go.id/vaksinasi-influenza-gratis",
    },
    {
        "source": "Kementerian Sosial RI",
        "category": "PHISHING_LINK",
        "title": "Situs Pendaftaran Bantuan Sosial Palsu",
        "claim_summary": (
            "Beredar tautan pendaftaran bantuan sosial senilai dua juta rupiah di luar situs "
            "resmi pemerintah."
        ),
        "fact_explanation": (
            "Informasi resmi bantuan sosial pemerintah hanya disalurkan melalui situs resmi "
            "berakhiran .go.id seperti cekbansos.kemensos.go.id. Tautan di luar domain tersebut "
            "adalah situs phishing yang dibuat untuk mencuri data KTP dan informasi pribadi."
        ),
        "verdict": "HOAX",
        "source_url": "https://cekbansos.kemensos.go.id/",
    },
    {
        "source": "Patroli Siber",
        "category": "FILE_APK",
        "title": "Modus Penipuan File APK Undangan dan Resi Paket",
        "claim_summary": (
            "File berakhiran .apk dikirim di grup WhatsApp dengan nama undangan pernikahan "
            "atau resi paket."
        ),
        "fact_explanation": (
            "File .apk yang dikirim lewat WhatsApp adalah modus pencurian data pribadi dan saldo "
            "rekening bank. Undangan resmi maupun resi pengiriman tidak pernah berbentuk file "
            "aplikasi. Bila terlanjur dipasang, segera matikan koneksi internet dan hubungi bank."
        ),
        "verdict": "HOAX",
        "source_url": "https://patrolisiber.id/modus-apk-undangan",
    },
]

# Casts are load-bearing: `$1` appears both in the SELECT list and in a
# comparison against a VARCHAR column, and Postgres cannot deduce one type for
# both ("inconsistent types deduced for parameter $1").
UPSERT_SOURCE = """
INSERT INTO fact_sources (name, base_url, is_trusted)
SELECT $1::varchar(100), $2::varchar(255), $3::boolean
WHERE NOT EXISTS (SELECT 1 FROM fact_sources WHERE name = $1::varchar(100))
"""

UPSERT_FACT = """
INSERT INTO fact_items (source_id, category, title, claim_summary, fact_explanation, verdict, source_url)
VALUES ($1, $2::category_enum, $3, $4, $5, $6::verdict_enum, $7)
ON CONFLICT DO NOTHING
"""


async def seed() -> dict[str, int]:
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url, timeout=10)
    inserted = 0
    try:
        for name, base_url, trusted in SOURCES:
            await conn.execute(UPSERT_SOURCE, name, base_url, trusted)

        for fact in FACTS:
            existing = await conn.fetchval(
                "SELECT id FROM fact_items WHERE source_url = $1", fact["source_url"]
            )
            source_id = await conn.fetchval("SELECT id FROM fact_sources WHERE name = $1", fact["source"])
            if existing:
                await conn.execute(
                    """
                    UPDATE fact_items
                    SET category = $2::category_enum, title = $3, claim_summary = $4,
                        fact_explanation = $5, verdict = $6::verdict_enum, source_id = $7
                    WHERE id = $1
                    """,
                    existing,
                    fact["category"],
                    fact["title"],
                    fact["claim_summary"],
                    fact["fact_explanation"],
                    fact["verdict"],
                    source_id,
                )
                continue

            await conn.execute(
                UPSERT_FACT,
                source_id,
                fact["category"],
                fact["title"],
                fact["claim_summary"],
                fact["fact_explanation"],
                fact["verdict"],
                fact["source_url"],
            )
            inserted += 1
    finally:
        await conn.close()

    return {"sources": len(SOURCES), "facts": len(FACTS), "inserted": inserted}


def main() -> None:
    configure_logging(get_settings().log_level)
    logger.info("knowledge seeded", extra=asyncio.run(seed()))


if __name__ == "__main__":
    main()
