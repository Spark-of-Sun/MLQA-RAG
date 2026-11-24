-- Column encryption, step 2 of 2 (KD-9; R-51 criterion 3; closes DEV-09 for columns; Q-36 default).
--
-- Drops the plaintext columns 0012_field_encryption shadowed with ciphertext. It refuses to run while any row still
-- has a plaintext value without its ciphertext: `make migrate` runs the re-encryption job
-- (tools/reencrypt_fields.py) between the two revisions, so on a database with data this only fails if that job
-- did not finish. The check reads every row: RLS is relaxed for the owner in this transaction only.

alter table documents no force row level security;
alter table chunks no force row level security;
alter table queries no force row level security;
alter table query_segments no force row level security;
alter table conversations no force row level security;
alter table users no force row level security;

do $$
declare
    missing text[] := array[]::text[];
begin
    if exists (select 1 from documents where title_ct is null or filename_ct is null) then
        missing := missing || 'documents';
    end if;
    if exists (select 1 from chunks where text_ct is null or (section is not null and section_ct is null)) then
        missing := missing || 'chunks';
    end if;
    if exists (select 1 from queries where question_ct is null or result_ct is null
               or (standalone_question is not null and standalone_question_ct is null)) then
        missing := missing || 'queries';
    end if;
    if exists (select 1 from query_segments where text is not null and text_ct is null) then
        missing := missing || 'query_segments';
    end if;
    if exists (select 1 from conversations where title_ct is null) then
        missing := missing || 'conversations';
    end if;
    if exists (select 1 from users where (email is not null and email_ct is null)
               or (name is not null and name_ct is null) or (phone is not null and phone_ct is null)) then
        missing := missing || 'users';
    end if;
    if cardinality(missing) > 0 then
        raise exception 'plaintext rows without ciphertext in %; run the re-encryption job: make reencrypt',
            array_to_string(missing, ', ');
    end if;
end
$$;

alter table documents drop column title, drop column filename;
alter table documents alter column title_ct set not null, alter column filename_ct set not null;

alter table chunks drop column text, drop column section;
alter table chunks alter column text_ct set not null;

alter table queries drop column question, drop column standalone_question, drop column result;
alter table queries alter column question_ct set not null, alter column result_ct set not null;

alter table query_segments drop column text;

alter table conversations drop column title;
alter table conversations alter column title_ct set not null;

alter table users drop column email, drop column name, drop column phone;

alter table documents force row level security;
alter table chunks force row level security;
alter table queries force row level security;
alter table query_segments force row level security;
alter table conversations force row level security;
alter table users force row level security;
