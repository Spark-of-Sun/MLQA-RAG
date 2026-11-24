-- Sentence-gated release (blueprint 4.4, 11.6, G7.7, G7.9, G7.11): every released sentence, in order, with the
-- validator's signed verdict. Written in the same transaction as its `segment.released` audit event, so a resumed
-- stream (Last-Event-ID) replays only sentences that were released and audited.
create table query_segments (
    query_id      uuid not null references queries (id) on delete cascade,
    seq           int not null check (seq > 0),
    org_id        uuid not null,
    workspace_id  uuid not null,
    user_id       uuid not null,
    kind          text not null check (kind in ('sentence', 'stripped', 'refusal')),
    text          text,
    text_sha256   text not null,
    verdict       text not null,
    citations     jsonb not null default '[]'::jsonb,
    audit_event_id bigint not null,
    created_at    timestamptz not null default now(),
    primary key (query_id, seq)
);
alter table query_segments enable row level security;
alter table query_segments force row level security;

alter table queries
    add column request_id   uuid,
    add column scope_hash   text,
    add column delivery     text not null default 'buffered' check (delivery in ('buffered', 'sentence')),
    add column state        text not null default 'completed' check (state in ('streaming', 'completed', 'failed')),
    add column released_sha256 text;
