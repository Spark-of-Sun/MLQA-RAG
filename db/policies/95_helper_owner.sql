-- Helper ownership (blueprint 10.3; R-32 criterion 6; DEV-48). Runs after every helper is (re)defined.
-- Every STABLE SECURITY DEFINER app_* lookup helper is owned by the NOLOGIN role policy_helper, which can only read.
-- Audit writers/readers and trigger functions stay with lmqa_owner (they write; R-32 criterion 9). The boot
-- self-test stays with lmqa_owner because information_schema grants are visible to the grantor only.

do $$
declare
    t record;
    f record;
begin
    -- policy_helper reads what the helpers read, through its own select-only policy (FORCE RLS applies to it).
    for t in
        select n.nspname, c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where c.relkind in ('r', 'p') and n.nspname in ('public', 'ops') and c.relname <> 'schema_migrations'
          and c.relname not like 'procrastinate%' and not c.relispartition
    loop
        execute format('grant select on %I.%I to policy_helper', t.nspname, t.relname);
        execute format('drop policy if exists helper_read on %I.%I', t.nspname, t.relname);
        execute format('create policy helper_read on %I.%I for select to policy_helper using (true)',
                       t.nspname, t.relname);
    end loop;
    execute 'grant usage on schema ops to policy_helper';
    for f in
        select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname like 'app\_%' and p.prosecdef and p.provolatile = 's'
          and p.prorettype <> 'trigger'::regtype and p.proname <> 'app_boot_self_test'
    loop
        execute format('alter function %s owner to policy_helper', f.sig);
    end loop;
end
$$;
