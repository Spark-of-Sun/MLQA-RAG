-- Column encryption, step 1 of 2 (blueprint 12.2, KD-9; R-51 criteria 2 to 5, R-53; DEV-09 columns; Q-36 default).
--
-- Adds a ciphertext column next to every plaintext content and contact column, the key tables the field cipher
-- needs, and workspace-month audit keys. Values are written by lmqa_keys.FieldCipher (AES-256-GCM, random 96-bit
-- nonce, associated data binding purpose, org_id, workspace_id, object ID and version; the key version travels in
-- the value header). The one-time re-encryption job (tools/reencrypt_fields.py, run by `make migrate` between this
-- revision and the next) fills the new columns from the old ones; 0013_drop_plaintext then drops the old ones.
--
--   documents.title, filename        -> title_ct, filename_ct              (document key)
--   chunks.text, section             -> text_ct, section_ct                (document key)
--   queries.question, standalone_question, result -> *_ct                  (workspace content key)
--   query_segments.text              -> text_ct                            (workspace content key)
--   conversations.title              -> title_ct                           (workspace content key)
--   users.email, name, phone         -> email_ct, name_ct, phone_ct        (platform contact key)
--   users.email_blind_index          HMAC-SHA256 under the platform blind-index key (R-51.5)
--
-- Full text: tsv and tsv_simple stop being generated from chunks.text. The writer stores them from the plaintext it
-- holds, stripped of positions (strip()), so the index keeps the set of lexemes of a passage but not their order.
-- That set is the remaining plaintext-derived data at rest; it goes when lexical search moves to Qdrant sparse
-- vectors (KD-4, Stage 4).

-- The owner rewrites rows under FORCE RLS only with RLS relaxed for this transaction; 15_force_rls.sql forces it
-- again on every migrate, and the statements at the end of this file do so already.
alter table chunks no force row level security;

alter table documents
    add column title_ct    bytea,
    add column filename_ct bytea,
    alter column title drop not null,
    alter column filename drop not null;

alter table chunks rename column text_ciphertext to text_ct;
alter table chunks
    add column section_ct bytea,
    alter column text drop not null,
    alter column tsv drop expression,
    alter column tsv_simple drop expression;
update chunks set tsv = strip(tsv), tsv_simple = strip(tsv_simple);

alter table queries
    add column question_ct            bytea,
    add column standalone_question_ct bytea,
    add column result_ct              bytea,
    alter column question drop not null,
    alter column result drop not null;

alter table query_segments add column text_ct bytea;

alter table conversations
    add column title_ct bytea,
    alter column title drop not null;

alter table users rename column email_ciphertext to email_ct;
alter table users
    add column name_ct  bytea,
    add column phone_ct bytea;
-- Two Auth0 identities may share an email address, so the blind index is a lookup index, not a uniqueness rule.
drop index if exists users_email_blind_index;
create index users_email_blind_index on users (email_blind_index) where email_blind_index is not null;

-- Platform keys: users belong to no single organization, so their contact fields use a platform CMK
-- (`lmqa-platform`) and a key wrapped by it. purpose 'contact' seals email, name and phone; 'blind_index' is the HMAC
-- key for equality lookups. Versioned; older versions stay readable.
create table platform_keys (
    purpose     text not null check (purpose in ('contact', 'blind_index')),
    key_version int not null check (key_version > 0),
    provider    text not null check (provider in ('aws_kms', 'openbao')),
    key_ref     text not null,
    wrapped_key bytea not null,
    state       text not null default 'active' check (state in ('active', 'retired', 'destroyed')),
    created_at  timestamptz not null default now(),
    primary key (purpose, key_version)
);

-- Daily cache keys (R-51.2): independent random keys, wrapped by a workspace content key version, for the scoped
-- answer cache in Valkey. Yesterday's key no longer matches, so cached entries expire with it.
create table cache_keys (
    org_id       uuid not null,
    workspace_id uuid not null,
    day          date not null,
    wrapped_key  bytea not null,
    wrapped_by   int not null,
    created_at   timestamptz not null default now(),
    primary key (workspace_id, day),
    foreign key (org_id, workspace_id, wrapped_by) references workspace_keys (org_id, workspace_id, key_version)
);

-- Workspace-month audit keys (KD-10, R-51.2): one X25519 pair per workspace per calendar month; workspace_id null is
-- the organization control chain. The private half is wrapped by the organization CMK version `wrapped_by`.
alter table audit_keys
    add column id           bigint generated always as identity,
    add column workspace_id uuid,
    add column wrapped_by   int;
update audit_keys k set wrapped_by = (select min(o.key_version) from org_keys o where o.org_id = k.org_id)
where k.wrapped_private_key is not null;
alter table audit_keys drop constraint audit_keys_pkey;
alter table audit_keys
    add primary key (id),
    add constraint audit_keys_scope_key unique nulls not distinct (org_id, workspace_id, month),
    add constraint audit_keys_workspace_fk foreign key (org_id, workspace_id) references workspaces (org_id, id),
    add constraint audit_keys_wrapped_by_fk foreign key (org_id, wrapped_by) references org_keys (org_id, key_version);

alter table chunks force row level security;
alter table platform_keys enable row level security;
alter table platform_keys force row level security;
alter table cache_keys enable row level security;
alter table cache_keys force row level security;
