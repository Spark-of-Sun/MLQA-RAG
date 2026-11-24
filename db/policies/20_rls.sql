-- Row-level security policies (blueprint 5.4). Re-applied on every migrate.
--
-- The access decision is app_can_read() in 11_access.sql: rules 1 to 8 of blueprint 5.4 and nothing else (KD-3).
-- The MVP rules 7a (visibility 'workspace') and 7b (document_shares) were migrated out (DEV-14, 0011_access_rules).
-- document_shares stays as a table for the frozen named_shares feature (task 3.6); no content policy reads it.

-- Shares: the owner sees every share of their documents, a recipient sees only their own share. A share row grants
-- no access to the document.
drop policy if exists document_shares_read on document_shares;
create policy document_shares_read on document_shares for select using (
    workspace_id = (select app_active_workspace())
    and (user_id = (select app_user_id()) or owner_id = (select app_user_id()))
);

-- Only the owner shares, only their own document, only with someone app_share_target_ok() allows.
drop policy if exists document_shares_insert on document_shares;
create policy document_shares_insert on document_shares for insert with check (
    workspace_id = (select app_active_workspace())
    and owner_id = (select app_user_id())
    and app_owns_document(document_id)
    and app_share_target_ok(user_id)
);

drop policy if exists documents_read on documents;
create policy documents_read on documents for select using (
    app_can_read(workspace_id, owner_id, visibility, matter_id, tier, id)
);

-- 5.5 upload tier ceiling (R-5.3): the uploader's own ceiling on the target (app_upload_ceiling in 11_access.sql).
drop policy if exists documents_insert on documents;
create policy documents_insert on documents for insert with check (
    workspace_id = (select app_active_workspace())
    and owner_id = (select app_user_id())
    and tier <= coalesce(app_upload_ceiling(visibility, matter_id), 0)
);

-- The owner may delete their own document. A recipient of a share may not.
drop policy if exists documents_delete on documents;
create policy documents_delete on documents for delete using (
    workspace_id = (select app_active_workspace())
    and owner_id = (select app_user_id())
);

drop policy if exists chunks_read on chunks;
create policy chunks_read on chunks for select using (
    app_can_read(workspace_id, owner_id, visibility, matter_id, tier, document_id)
);

drop policy if exists queries_own on queries;
create policy queries_own on queries for all
    using (user_id = (select app_user_id()) and workspace_id = (select app_active_workspace()))
    with check (user_id = (select app_user_id()) and workspace_id = (select app_active_workspace()));

-- Chats are private to their author: not the admin, not other members, not the Super Admin.
drop policy if exists conversations_own on conversations;
create policy conversations_own on conversations for all
    using (user_id = (select app_user_id()) and workspace_id = (select app_active_workspace()))
    with check (user_id = (select app_user_id()) and workspace_id = (select app_active_workspace()));

-- The subquery is itself filtered by queries_own, so a ledger row follows its query.
drop policy if exists retrieval_records_own on retrieval_records;
create policy retrieval_records_own on retrieval_records for all
    using (exists (select 1 from queries q where q.id = query_id))
    with check (exists (select 1 from queries q where q.id = query_id));

-- Released segments follow their query: only the asker reads them (DEF-63).
drop policy if exists query_segments_own on query_segments;
create policy query_segments_own on query_segments for all
    using (user_id = (select app_user_id()) and workspace_id = (select app_active_workspace()))
    with check (user_id = (select app_user_id()) and workspace_id = (select app_active_workspace()));
