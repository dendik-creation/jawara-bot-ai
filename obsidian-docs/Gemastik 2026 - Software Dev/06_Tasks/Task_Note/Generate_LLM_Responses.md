# Catatan — Generate LLM Responses

Task: [[Generate LLM Responses]] · Indeks: [[00_Sprint_1_Completion_Notes]]

---

## 1. Keputusan yang harus diambil dulu: provider LLM

Task ini menyatakan secara eksplisit: *"LLM provider is undecided in the vault — resolve this before starting."* Keputusan diambil.

> **Provider produksi: Anthropic Claude Haiku** (`LLM_MODEL=claude-haiku-4-5-20251001`).

Alasan, berurut sesuai bobotnya untuk produk ini:

1. **Kepatuhan pada kontrak output yang kaku.** Balasan wajib memuat empat bagian, berurutan, dengan setiap baris draf forward diawali `>`. Makin sering model gagal, makin sering pengguna menerima balasan hasil komposer template yang terasa kaku.
2. **Kefasihan Bahasa Indonesia pada register sopan-non-teknis** yang dituntut persona ("Bapak/Ibu", tanpa jargon medis).
3. **Latensi dan biaya** masuk anggaran <3.0 detik untuk panggilan per pesan.

Kontrak `/v1/generate` tetap provider-agnostic: `LLM_PROVIDER=openai` (`gpt-4o-mini`) sudah diimplementasikan penuh sebagai pembanding, dan tidak ada kode di luar `ml-service/app/llm/` yang tahu vendor mana yang menjawab.

Dokumen yang perlu ikut diperbarui: [[03_Tech_Stack]] §4 (sudah), [[01_LLM_System_Prompt]] (sudah).

---

## 2. Yang tidak bisa diverifikasi: generasi LLM sungguhan

**`ANTHROPIC_API_KEY` kosong di environment ini**, jadi jalur yang benar-benar dijalankan adalah `template` — komposer deterministik offline.

Konsekuensi konkret:

| Kriteria penerimaan | Status |
| :--- | :--- |
| Output selalu memuat 4 bagian | ✅ diuji — validator + komposer, 5 kasus few-shot terdokumentasi |
| Draf forward selalu diawali `>` tiap baris | ✅ diuji |
| Output LLM rusak tertangkap sebelum dikirim | ✅ diuji dengan provider palsu yang sengaja mengembalikan teks tanpa struktur |
| 5 input few-shot konsisten dengan contoh terdokumentasi | ⚠️ **diverifikasi terhadap komposer template, bukan terhadap Claude Haiku** |

Baris terakhir itu yang belum tuntas. Struktur dan nada sudah dijamin oleh kode; kesamaan *diksi* dengan lima contoh di [[01_LLM_System_Prompt]] baru bisa dinilai setelah ada API key.

### Cara menyelesaikannya

```bash
# .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Lalu `docker compose up -d ml-service` dan cek `GET /v1/ready` — kalau key hilang, `degraded_reasons` akan memuat `anthropic_key_missing` dan service **tetap ready** dengan komposer template. Itu disengaja: pipeline yang tidak bisa menjawab sama sekali lebih buruk daripada pipeline yang menjawab dengan template.

---

## 3. Komposer template bukan sekadar tambalan

Ia punya dua peran permanen, bukan hanya "sebelum ada key":

1. **Jalur perbaikan.** Kalau LLM sungguhan mengembalikan output yang gagal validasi, output itu dibuang dan diganti komposer. `result.fallback_used = true` dan `fallback_reason` masuk ke log — jadi terlihat berapa sering model melanggar kontrak.
2. **Kemandirian CI/demo.** Seluruh pipeline bisa dijalankan tanpa koneksi internet dan tanpa vendor.

Batasnya jelas dan disengaja: komposer **tidak pernah** merumuskan kalimat yang tidak ada di knowledge base. Ia menyusun ulang `fact_explanation` yang diambil dari retrieval plus satu kalimat saran per kategori. Itulah kenapa ia aman dipakai sebagai fallback.

---

## 4. Fallback statis saat LLM timeout

Task menyebut ini "resilience feature, defer unless time allows". Ternyata ia jatuh gratis: komposer template *adalah* fallback statis itu. `MlError` dari provider ditangkap di endpoint `/v1/generate`, dicatat, lalu dijawab komposer — bukan diteruskan sebagai error ke gateway.

---

**Related:** [[01_LLM_System_Prompt]] · [[04_ML_Service]] · [[03_Tech_Stack]] · [[Open_Decisions_Carried_Forward]]
