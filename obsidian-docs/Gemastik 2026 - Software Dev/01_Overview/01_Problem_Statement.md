# Masalah & Ruang Lingkup Proyek

## 1. Context & Problem Statement

### 1.1 Akar Masalah: Disinformasi & Kejahatan Siber di "Dark Social"
Penyebaran **disinformasi kesehatan**, **narasi palsu**, dan **penipuan siber terorganisir** di Indonesia mengalami pergeseran masif dari media sosial publik (seperti Facebook/X) ke platform percakapan privat (*Dark Social*)—khususnya **WhatsApp**.

* **Karakteristik WhatsApp Group:** Informasi menyebar di dalam lingkaran kepercayaan (*circle of trust*) seperti grup keluarga, alumni, dan lingkungan RT/RW. Ketika pesan bohong atau link berbahaya dikirimkan oleh kerabat terdekat, tingkat kepercayaan korban meningkat secara signifikan (*Social Engineering*).
* **Kendala End-to-End Encryption (E2EE):** Karena WhatsApp menggunakan enkripsi *End-to-End*, platform atau lembaga fact-checking publik (seperti Mafindo, Cekfakta, atau Kominfo) **tidak memiliki akses langsung** untuk memantau, memfilter, atau mengintervensi pesan secara otomatis di ruang percakapan privat tersebut.

### 1.2 Target Audiens Terdampak: Demografi Rentan Digital & Lansia
1. **Lansia (Senior Citizens 50+):** Mengalami penurunan literasi digital critical thinking, sulit membedakan visual infografis asli vs editan, dan rentan percaya pada klaim kesehatan herbal/obat ajaib.
2. **Keluarga & Pengurus Rumah Tangga:** Sering dijadikan target penipuan finansial berbasis modifikasi file (seperti file `.APK` bermodus kurir paket, surat undangan pernikahan digital, atau tagihan PLN).
3. **Masyarakat Umum:** Rentan terhadap penipuan program sosial pemerintah (bansos palsu, kuota gratis) dan phishing perbankan/e-wallet.

---

## 2. Mengapa Solusi Eksisting Belum Efektif?

| Solusi Eksisting | Keterbatasan & Kelemahan Utama |
| :--- | :--- |
| **Web Fact-Checker (Mafindo / TurnBackHoax / Cekfakta)** | **Pasif & Reaktif:** Pengguna harus menyadari kecurigaan terlebih dahulu, keluar dari WhatsApp, membuka browser, dan mencari kata kunci secara manual. Hambatan *user friction* sangat tinggi untuk lansia. |
| **Aplikasi Antivirus & Parental Control (Family Link / Avast)** | **Fokus Infrastruktur Perangkat:** Hanya memindai malware tingkat sistem perkasas, tidak menganalisis narasi disinformasi kontekstual Bahasa Indonesia, hoaks kesehatan, atau manipulasi rekayasa sosial (*Social Engineering*). |
| **Penyuluhan & Literasi Manual (Sosialisasi Offline)** | **Tidak Scalable & Ketinggalan Zaman:** Kecepatan sosialisasi manual kalah jauh dari laju pembuatan hoaks baru berbasis AI (*deepfake / synthetic text*). |
| **Bot Fact-Checker WhatsApp Generasi Pertama** | **Kaku & Tidak Empatik:** Menggunakan balasan template artikel formal yang panjang, kaku, dan membingungkan lansia. Tidak menyediakan draf balasan untuk dikirimkan kembali ke grup. |

---

## 3. Infrastruktur & Solusi JAWARA (WAHA Self-Hosted Engine)

Sistem **JAWARA: Jaringan Asisten WhatsApp Anti-Rekayasa & Ancaman** dibangun menggunakan engine **WAHA (WhatsApp HTTP API)** yang di-host secara mandiri (*self-hosted via Docker*). Pilihan ini memberikan keuntungan:
* **Kontrol Penuh & Tanpa Biaya Per-Pesan:** Mengeliminasi ketergantungan biaya per-pesan WhatsApp Cloud API.
* **Integrasi Native Webhook & REST API:** Menerima event pesan dan mengirimkan pesan balasan melalui local REST endpoints (`/api/sendText`, `/api/sendMedia`).
* **Privasi Terjaga:** Seluruh data komunikasi hanya melintasi server internal tim/instansi tanpa pihak ketiga.

---

## 4. Cakupan Informasi & Multi-Threat Domain

Sistem **JAWARA** dirancang untuk menganalisis dan menangani 5 (lima) domain ancaman utama:

1. **Hoaks Kesehatan (Health Misinformation):**
   - Klaim herbal/tanpa tindakan medis untuk penyakit kronis (katarak, kanker, diabetes).
   - Isu keamanan vaksin, obat-obatan tanpa izin BPOM, dan metode pengobatan berbahaya.
2. **Penipuan Finansial & Rekening Fraud:**
   - Modus transfer salah kirim, pinjaman online ilegal, hadiah undian berhadiah palsu.
   - Pengecekan nomor rekening/e-wallet penipu yang terintegrasi dengan basis data kejahatan finansial.
3. **Malicious File & Malware Installation (`.APK` Scams):**
   - File aplikasi Android berbahaya yang menyamar sebagai dokumen foto (`.apk`), undangan pernikahan, bukti resi kurir, atau surat tilang elektronik.
4. **Phishing & Credential Harvesting Links:**
   - Link tautan yang meniru situs web resmi perbankan, portal bansos pemerintah, atau promo kuota internet.
5. **Isu Publik & Berita Disinformasi Umum:**
   - Hoaks kebencanaan, isu politik provokatif lokal, dan manipulasi kebijakan pemerintah.

---

**Related:** [[02_Value_Proposition]] · [[03_Pitching_Narrative]] · [[01_System_Architecture]]