-- Retrieval refinements (blueprint 11.1, 11.3).

-- Exact-term search. The 'english' tsvector stems words ("payments" -> "payment") and drops stop words, which is
-- right for prose but loses exact identifiers: drug names, dosages, statute and clause numbers ("164.312(a)(2)",
-- "10 mg"). A second, unstemmed 'simple' tsvector keeps them, and retrieval runs both. Existing rows are filled
-- when the column is added.
alter table chunks
    add column tsv_simple tsvector
        generated always as (to_tsvector('simple', coalesce(section, '') || ' ' || text)) stored;
create index chunks_tsv_simple on chunks using gin (tsv_simple);

-- Neighbour expansion reads the chunks next to a hit (same document, ordinal +/- 1).
create index chunks_document_ordinal on chunks (document_id, ordinal);

-- Embedding cache: a passage already embedded with the same model is not sent to the provider again (re-uploads,
-- duplicate exhibits, re-indexing after a chunker change). Keyed per organization, so whether a text was seen
-- before can never be inferred across customers. Used only by the ingestion worker (lmqa_system); no RLS policy
-- because no request-scoped role can reach it.
create table embedding_cache (
    org_id      uuid not null references organizations (id) on delete cascade,
    model       text not null,
    text_sha256 text not null,
    embedding   vector(768) not null,
    created_at  timestamptz not null default now(),
    primary key (org_id, model, text_sha256)
);
