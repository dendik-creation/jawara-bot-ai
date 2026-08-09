from app.pipeline.url_extractor import SHORTENER_DOMAINS, extract_urls, has_shortlink


def test_extracts_scheme_url_from_sentence():
    urls = extract_urls("Benar gak link ini http://bansos-pemerintah-2026.com buat klaim bantuan?")
    assert [url.url for url in urls] == ["http://bansos-pemerintah-2026.com"]
    assert urls[0].domain == "bansos-pemerintah-2026.com"


def test_extracts_bare_shortener_without_scheme():
    # The acceptance case: a shortener typed without `http://`. Its TLD is not in
    # the general TLD list, so this only works because shorteners are matched by
    # exact domain.
    urls = extract_urls("klik bit.ly/hadiah2026 sekarang ya")
    assert urls[0].url == "http://bit.ly/hadiah2026"
    assert urls[0].is_shortlink
    assert has_shortlink(urls)


def test_handles_multiple_urls_in_order_without_duplicates():
    urls = extract_urls(
        "cek https://kemkes.go.id/a lalu tinyurl.com/xyz dan lagi https://kemkes.go.id/a"
    )
    assert [url.url for url in urls] == ["https://kemkes.go.id/a", "http://tinyurl.com/xyz"]


def test_trailing_sentence_punctuation_is_not_part_of_the_url():
    urls = extract_urls("buka https://cekbansos.kemensos.go.id/, lalu isi data.")
    assert urls[0].url == "https://cekbansos.kemensos.go.id/"


def test_defanged_link_is_restored_and_flagged():
    urls = extract_urls("jangan buka hxxp://phishing-site[.]com/login")
    assert urls[0].url == "http://phishing-site.com/login"
    assert urls[0].was_defanged


def test_ip_literal_host_is_flagged():
    urls = extract_urls("login di http://192.168.10.5/verify")
    assert urls[0].is_ip_host


def test_www_prefix_gets_a_scheme_and_a_clean_domain():
    urls = extract_urls("kunjungi www.kemkes.go.id/berita")
    assert urls[0].url == "http://www.kemkes.go.id/berita"
    assert urls[0].domain == "kemkes.go.id"


def test_ordinary_indonesian_sentence_yields_no_urls():
    # Bare-domain matching is the easiest way to invent URLs out of prose.
    assert extract_urls("silakan coba.in dulu ya pak, nanti saya kabari") == []
    assert extract_urls("dll. jadi begitu ceritanya") == []


def test_registrable_domain_handles_indonesian_second_level_suffixes():
    urls = extract_urls("https://cekbansos.kemensos.go.id/x")
    assert urls[0].registrable_domain == "kemensos.go.id"


def test_no_urls_in_empty_input():
    assert extract_urls("") == []
    assert extract_urls(None) == []


def test_known_shorteners_are_recognised():
    for domain in ("bit.ly", "tinyurl.com", "s.id", "cutt.ly"):
        assert domain in SHORTENER_DOMAINS
        assert extract_urls(f"https://{domain}/abc")[0].is_shortlink
