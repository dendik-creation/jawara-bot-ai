"""Seed a labeled train + held-out eval dataset for the threat classifier.

Usage: `python -m app.scripts.seed_dataset_samples`

No real, collected corpus exists for this project yet (04_AI_and_ML/
04_Datasets_and_Operator_Feedback.md names dataset *sources* generically —
CURATED/OPERATOR_FEEDBACK/IMPORTED/APPROVED_INTERNAL — but no specific real
data source). These are synthetic, templated Indonesian WhatsApp-style
messages across the six `VALID_LABELS`
(`app.services.datasets.VALID_LABELS`), grounded in tone/style from the real
few-shot examples in `04_AI_and_ML/01_LLM_System_Prompt.md` and the curated
claims in `seed_facts.py` — enough to prove the training/evaluation/promotion
pipeline works end to end, not production-grade accuracy.

Requires at least one operator account to already exist (`created_by`/
`added_by` are NOT NULL FKs to `operators`) — run `create_operator` first.

Idempotent by (dataset name, version): a dataset already at VALIDATED/ARCHIVED
is left untouched and samples are not re-inserted. A dataset stuck in DRAFT
from a previous partial run is reported, not auto-repaired — re-run after
clearing it manually if that happens.
"""

import asyncio
import itertools
import logging
import random

import asyncpg

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.datasets import apply_dataset_action, create_dataset

logger = logging.getLogger("app.scripts.seed_dataset_samples")

_SEED = 20260812  # fixed, so re-running before VALIDATE regenerates the same text
_TRAIN_PER_LABEL = 40
_EVAL_PER_LABEL = 10

# --------------------------------------------------------------------------
# Templated content per label. Combinatorics (remedies x ailments x phrasing,
# etc.) give far more unique sentences than needed per label without hand
# writing hundreds of lines — and the repeated trigger vocabulary per label
# ("transfer"/"admin" for fraud, "instal"/"apk" for FILE_APK, ...) is exactly
# the signal a TF-IDF classifier needs.
# --------------------------------------------------------------------------


def _health_hoax() -> list[str]:
    remedies = [
        "daun kelor", "rebusan daun sirih merah", "air rebusan serai", "madu hutan asli",
        "minyak kutus-kutus", "jahe merah campur kunyit", "daun binahong", "air kelapa muda hijau",
        "teh pegagan", "propolis murni", "rebusan daun kitolod", "air rebusan bawang putih",
    ]
    ailments = [
        "kanker stadium akhir", "diabetes permanen", "katarak tanpa operasi", "stroke dalam semalam",
        "darah tinggi seketika", "asam urat total", "batu ginjal", "tumor payudara",
        "penyakit jantung", "kolesterol tinggi", "gagal ginjal", "radang sendi",
    ]
    templates = [
        "Info kesehatan: {remedy} terbukti bisa menyembuhkan {ailment} tanpa efek samping, sudah banyak yang buktikan",
        "Dokter di rumah sakit besar sampai kaget, {remedy} ternyata ampuh sembuhkan {ailment} cuma dalam seminggu",
        "Jangan buang {remedy} di rumah, rutin minum bisa sembuhkan {ailment} tanpa perlu obat dokter",
        "Viral, {remedy} disebut obat alami paling ampuh untuk {ailment}, bagikan sebelum dihapus",
        "Nenek saya sembuh dari {ailment} cuma pakai {remedy}, resep turun temurun yang jarang orang tahu",
    ]
    return [
        template.format(remedy=remedy, ailment=ailment)
        for template, remedy, ailment in itertools.product(templates, remedies, ailments)
    ]


def _financial_fraud() -> list[str]:
    hooks = [
        "Anda terpilih sebagai pemenang undian", "Nomor Anda menang hadiah tunai",
        "Rekening Anda terdeteksi transaksi mencurigakan", "Kartu ATM Anda akan segera diblokir",
        "Anda mendapat bantuan langsung tunai", "Ada transfer masuk tertunda ke rekening Anda",
        "BPJS Anda nonaktif karena tunggakan", "Paket Anda tertahan karena bea masuk belum dibayar",
    ]
    asks = [
        "segera transfer biaya admin agar hadiah bisa dicairkan",
        "kirim kode OTP yang baru saja dikirim ke nomor Anda",
        "balas dengan nomor rekening dan PIN untuk verifikasi",
        "bayar biaya pajak hadiah lewat transfer bank",
        "klik tombol konfirmasi dan masukkan password mobile banking",
        "hubungi customer service dan berikan data kartu lengkap",
    ]
    templates = [
        "{hook}, {ask} dalam waktu 1x24 jam atau hadiah hangus",
        "{hook}. Untuk proses selanjutnya mohon {ask}",
        "Pemberitahuan resmi: {hook}, mohon {ask} secepatnya",
        "{hook}! Jangan sampai terlambat, {ask} sekarang juga",
    ]
    return [
        template.format(hook=hook, ask=ask) for template, hook, ask in itertools.product(templates, hooks, asks)
    ]


def _general_news() -> list[str]:
    topics = [
        "vaksinasi influenza gratis di puskesmas", "prakiraan cuaca ekstrem pekan ini",
        "jadwal perpanjangan SIM keliling", "pembukaan pendaftaran CPNS tahun ini",
        "program vaksinasi campak untuk balita", "pemadaman listrik terjadwal minggu depan",
        "perbaikan jalan tol akhir pekan", "hasil sidang isbat penentuan hari raya",
    ]
    sources = [
        "Kementerian Kesehatan RI", "BMKG", "Kepolisian Republik Indonesia",
        "Badan Kepegawaian Negara", "Dinas Kesehatan setempat", "PLN",
        "Kementerian PUPR", "Kementerian Agama RI",
    ]
    templates = [
        "{source} mengumumkan {topic}, masyarakat diimbau memperhatikan informasi resmi",
        "Menurut siaran pers {source}, {topic} akan berlangsung mulai minggu depan",
        "{source} resmi merilis informasi terkait {topic} melalui kanal resmi",
        "Update terbaru dari {source} soal {topic}, cek jadwal lengkapnya di situs resmi",
    ]
    return [
        template.format(source=source, topic=topic)
        for template, source, topic in itertools.product(templates, sources, topics)
    ]


def _phishing_link() -> list[str]:
    lures = [
        "cek status bantuan sosial 2026", "verifikasi ulang akun mobile banking",
        "klaim saldo gratis dari dompet digital", "update data BPJS Ketenagakerjaan",
        "aktivasi ulang akun media sosial", "konfirmasi resi paket yang tertahan",
        "verifikasi email agar akun tidak ditutup", "klaim cashback belanja online",
        "perbarui data rekening sebelum diblokir", "ambil kembali poin reward yang hangus",
        "verifikasi nomor agar tidak kena suspend", "cek tagihan listrik yang menunggak",
        "klaim voucher gratis ongkir hari ini",
    ]
    templates = [
        "Silakan {lure} melalui tautan berikut sebelum batas waktu habis, klik link ini sekarang",
        "Klik link di bawah untuk {lure}, data Anda akan diproses otomatis",
        "Link resmi untuk {lure} sudah kami kirimkan, segera buka dan isi formulir",
        "Jangan lewatkan, {lure} hanya lewat tautan ini, berlaku terbatas hari ini saja",
        "Mohon segera {lure} lewat link resmi berikut agar layanan tidak terganggu",
    ]
    return [template.format(lure=lure) for template, lure in itertools.product(templates, lures)]


def _file_apk() -> list[str]:
    disguises = [
        "undangan pernikahan digital", "resi pengiriman paket", "slip gaji bulan ini",
        "surat tilang elektronik", "sertifikat vaksin digital", "faktur pembayaran listrik",
        "kartu ucapan lebaran", "dokumen tagihan BPJS", "surat panggilan kerja",
        "bukti transfer bank", "undangan rapat kantor", "kartu keluarga digital",
    ]
    templates = [
        "Silakan buka {disguise} melalui aplikasi terlampir, instal dulu untuk bisa melihat isinya",
        "Ini {disguise} untuk Anda, mohon install file apk berikut agar bisa dibuka di HP",
        "File {disguise} sudah saya kirim dalam bentuk aplikasi, tolong pasang lalu buka ya",
        "Cek {disguise} Anda di aplikasi ini, install dulu baru bisa login",
        "Mohon segera instal aplikasi {disguise} berikut supaya tidak ketinggalan info",
    ]
    return [template.format(disguise=disguise) for template, disguise in itertools.product(templates, disguises)]


def _not_a_threat() -> list[str]:
    subjects = [
        "ketemuan jam 7 malam", "kerja kelompok besok sore", "jalan-jalan ke mall akhir pekan",
        "makan siang bareng tim", "belajar bareng buat ujian", "olahraga pagi di lapangan",
        "nonton film di bioskop", "beres-beres rumah weekend ini", "rapat divisi besok pagi",
        "les bahasa Inggris sore ini",
    ]
    templates = [
        "Oke jadi {subject} ya, kabarin kalau ada perubahan",
        "Gimana kalau kita {subject}? aku free kok",
        "Udah siap belum buat {subject} nanti",
        "Makasih ya udah diingetin soal {subject}",
        "Btw jangan lupa {subject}, aku otw kesana",
    ]
    fixed = [
        "Makasih infonya, aku otw ke kantor sekarang",
        "Selamat ulang tahun, semoga sehat selalu dan panjang umur",
        "Aku udah sampai rumah, kamu udah makan belum",
        "Cuaca hari ini adem banget, enak buat jalan santai",
        "Anak-anak lagi main di taman deket rumah",
    ]
    generated = [template.format(subject=subject) for template, subject in itertools.product(templates, subjects)]
    return generated + fixed


_GENERATORS = {
    "HEALTH_HOAX": _health_hoax,
    "FINANCIAL_FRAUD": _financial_fraud,
    "GENERAL_NEWS": _general_news,
    "PHISHING_LINK": _phishing_link,
    "FILE_APK": _file_apk,
    "NOT_A_THREAT": _not_a_threat,
}


def _split_samples() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Deterministic shuffle then slice — train/eval never overlap by construction."""
    rng = random.Random(_SEED)
    train: dict[str, list[str]] = {}
    eval_: dict[str, list[str]] = {}
    for label, generator in _GENERATORS.items():
        texts = sorted(set(generator()))
        rng.shuffle(texts)
        needed = _EVAL_PER_LABEL + _TRAIN_PER_LABEL
        if len(texts) < needed:
            raise RuntimeError(f"{label}: only {len(texts)} unique templated samples, need {needed}")
        eval_[label] = texts[:_EVAL_PER_LABEL]
        train[label] = texts[_EVAL_PER_LABEL : _EVAL_PER_LABEL + _TRAIN_PER_LABEL]
    return train, eval_


async def _get_seed_operator(conn: asyncpg.Connection) -> str:
    operator_id = await conn.fetchval("SELECT id FROM operators ORDER BY created_at LIMIT 1")
    if operator_id is None:
        raise RuntimeError("no operator account exists — run `app.scripts.create_operator` first")
    return str(operator_id)


async def _ensure_dataset(
    conn: asyncpg.Connection, name: str, version: int, description: str, operator_id: str, samples: dict[str, list[str]]
) -> str:
    existing = await conn.fetchrow(
        "SELECT id, status::text AS status FROM datasets WHERE name = $1 AND version = $2", name, version
    )
    if existing is not None:
        if existing["status"] in ("VALIDATED", "ARCHIVED"):
            logger.info("dataset already %s, skipping", existing["status"], extra={"dataset_name": name})
            return str(existing["id"])
        raise RuntimeError(
            f"dataset '{name}' v{version} exists but is {existing['status']} — "
            "left over from a partial run, clean it up manually before re-seeding"
        )

    settings = get_settings()
    dataset = await create_dataset(name, version, "APPROVED_INTERNAL", description, operator_id, settings=settings)
    dataset_id = dataset["id"]

    for label, texts in samples.items():
        for text in texts:
            await conn.execute(
                """
                INSERT INTO dataset_samples (dataset_id, text, label, added_by)
                VALUES ($1, $2, $3, $4)
                """,
                dataset_id,
                text,
                label,
                operator_id,
            )

    result = await apply_dataset_action(dataset_id, action="VALIDATE", settings=settings)
    if result["status"] != "VALIDATED":
        raise RuntimeError(f"dataset '{name}' failed validation: {result['validation_notes']}")

    logger.info("dataset seeded and validated", extra={"dataset_name": name, "sample_count": result["sample_count"]})
    return dataset_id


async def seed() -> dict[str, str]:
    settings = get_settings()
    train_samples, eval_samples = _split_samples()

    conn = await asyncpg.connect(settings.database_url, timeout=10)
    try:
        operator_id = await _get_seed_operator(conn)
        train_id = await _ensure_dataset(
            conn, "core-detection-train", 1, "Synthetic training set for the core threat classifier", operator_id, train_samples
        )
        eval_id = await _ensure_dataset(
            conn, "core-detection-eval", 1, "Held-out evaluation set for the core threat classifier", operator_id, eval_samples
        )
    finally:
        await conn.close()

    return {"train_dataset_id": train_id, "eval_dataset_id": eval_id}


def main() -> None:
    configure_logging(get_settings().log_level)
    logger.info("dataset samples seeded", extra=asyncio.run(seed()))


if __name__ == "__main__":
    main()
