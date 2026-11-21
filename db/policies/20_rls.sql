-- Row-level security policies (blueprint 5.4). Re-applied on every migrate.
--
-- MVP access decision, in order:
--   1. membership, workspace or organization not active             -> deny (app_active_workspace() is NULL)
--   3. the document is the caller's own                               -> allow
--   4/5. visibility 'workspace' (shared with the whole workspace)     -> allow for its admin and members
--   5'. an explicit share to the caller (document_shares)             -> allow
--   8. anything else, including another member's private document    -> deny
-- Admins do NOT read members' private documents unless the member shared that document with them (rule 7 needs a
-- break-glass session, a later stage). Matters, walls, tiers and emergency access (rules 2, 5, 6) are later stages;
-- see docs/mvp.md.

-- Shares: the owner sees every share of their documents, a recipient sees only their own share.
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
    workspace_id = (select app_active_workspace())
    and (visibility = 'workspace' or owner_id = (select app_user_id())
         or exists (select 1 from document_shares s where s.document_id = documents.id
                    and s.user_id = (select app_user_id())))
);

-- Members may add only private documents; the admin may also share with the workspace.
drop policy if exists documents_insert on documents;
create policy documents_insert on documents for insert with check (
    workspace_id = (select app_active_workspace())
    and owner_id = (select app_user_id())
    and (visibility = 'private' or (select app_active_role()) = 'admin')
);

-- The owner may delete; the admin may also delete shared workspace documents. A recipient of a share may not.
drop policy if exists documents_delete on documents;
create policy documents_delete on documents for delete using (
    workspace_id = (select app_active_workspace())
    and (owner_id = (select app_user_id())
         or (visibility = 'workspace' and (select app_active_role()) = 'admin'))
);

drop policy if exists chunks_read on chunks;
create policy chunks_read on chunks for select using (
    workspace_id = (select app_active_workspace())
    and (visibility = 'workspace' or owner_id = (select app_user_id())
         or exists (select 1 from document_shares s where s.document_id = chunks.document_id
                    and s.user_id = (select app_user_id())))
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
