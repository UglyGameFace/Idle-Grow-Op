begin;

create or replace function public.idle_grow_save_scoped_records(
    p_global_accounts jsonb,
    p_guild_profiles jsonb,
    p_guild_worlds jsonb
)
returns void
language plpgsql
set search_path = public
as $$
begin
    insert into public.global_accounts (user_id, data)
    select
        (record ->> 'user_id')::bigint,
        coalesce(record -> 'data', '{}'::jsonb)
    from jsonb_array_elements(coalesce(p_global_accounts, '[]'::jsonb)) as record
    on conflict (user_id) do update
    set data = excluded.data;

    insert into public.guild_profiles (guild_id, user_id, data)
    select
        (record ->> 'guild_id')::bigint,
        (record ->> 'user_id')::bigint,
        coalesce(record -> 'data', '{}'::jsonb)
    from jsonb_array_elements(coalesce(p_guild_profiles, '[]'::jsonb)) as record
    on conflict (guild_id, user_id) do update
    set data = excluded.data;

    insert into public.guild_worlds (guild_id, data)
    select
        (record ->> 'guild_id')::bigint,
        coalesce(record -> 'data', '{}'::jsonb)
    from jsonb_array_elements(coalesce(p_guild_worlds, '[]'::jsonb)) as record
    on conflict (guild_id) do update
    set data = excluded.data;
end;
$$;

revoke all on function public.idle_grow_save_scoped_records(jsonb, jsonb, jsonb)
    from public, anon, authenticated;
grant execute on function public.idle_grow_save_scoped_records(jsonb, jsonb, jsonb)
    to service_role;

insert into public.app_schema_migrations (version)
values ('003_atomic_scoped_record_batch')
on conflict (version) do nothing;

commit;
