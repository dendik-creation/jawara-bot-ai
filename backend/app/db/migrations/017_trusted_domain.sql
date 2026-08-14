-- ==========================================================
-- 017 — Trusted official-domain recognition for URL safety (!link false-positive fix)
--
-- `fact_sources` is already the Knowledge Base's one source-of-truth model
-- (`is_trusted`, `reliability_score` from migration 016) — this migration
-- does not introduce a second "TrustedDomain" table. `normalized_domain` is
-- the exact hostname the URL-safety pipeline matches against
-- (`app.pipeline.url_extractor.normalize_domain`, `app.services.knowledge.
-- lookup_trusted_sources`): scheme/`www.`/path/query/fragment stripped,
-- everything else — including subdomains — kept as-is. It is deliberately
-- NOT collapsed to an eTLD+1 registrable domain: the seeded "Kementerian
-- Sosial RI" source is trusted for exactly `cekbansos.kemensos.go.id`, and
-- collapsing that to `kemensos.go.id` would make it stop matching the URL it
-- was entered for.
--
-- Nullable, not backfilled to a required value: rows created outside the
-- operator CRUD path (raw SQL fixtures, the ingestion adapters' own
-- `fact_sources` inserts) never populated it and must keep working — a NULL
-- `normalized_domain` simply never participates in trusted-domain matching,
-- same as before this migration existed. Existing rows are backfilled on a
-- best-effort basis so the five documented seed sources (PLN, Kemenkes,
-- Kemensos/cekbansos, Patroli Siber, TurnBackHoax) start participating
-- immediately without an operator having to re-save them.
--
-- The partial unique index (`WHERE normalized_domain IS NOT NULL`) is the
-- "prevent duplicate domains" control from the Control Panel spec — it does
-- not touch the many existing NULL rows.
-- ==========================================================

ALTER TABLE fact_sources ADD COLUMN IF NOT EXISTS normalized_domain TEXT;

UPDATE fact_sources
SET normalized_domain = lower(
    regexp_replace(
        regexp_replace(
            regexp_replace(trim(base_url), '^[a-zA-Z][a-zA-Z0-9+.-]*://', ''),
            '^www\.', ''
        ),
        '[/?#].*$', ''
    )
)
WHERE normalized_domain IS NULL
  AND base_url IS NOT NULL
  AND trim(base_url) <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_sources_normalized_domain
    ON fact_sources (normalized_domain) WHERE normalized_domain IS NOT NULL;
