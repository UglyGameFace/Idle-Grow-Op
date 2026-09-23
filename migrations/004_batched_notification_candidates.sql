begin;

create or replace function public.idle_grow_has_pending_notification_work(
    p_data jsonb
)
returns boolean
language sql
immutable
set search_path = public
as $$
    select
        coalesce(p_data #>> '{settings,notifications}', 'true') <> 'false'
        and (
            exists (
                select 1
                from jsonb_array_elements(
                    case
                        when jsonb_typeof(p_data -> 'plants') = 'array'
                        then p_data -> 'plants'
                        else '[]'::jsonb
                    end
                ) as plant
                where coalesce(plant ->> 'notified', 'false') <> 'true'
            )
            or exists (
                select 1
                from jsonb_array_elements(
                    case
                        when jsonb_typeof(p_data -> 'processing_queue') = 'array'
                        then p_data -> 'processing_queue'
                        else '[]'::jsonb
                    end
                ) as batch
                where coalesce(batch ->> 'notified', 'false') <> 'true'
            )
        );
$$;

drop index if exists public.guild_profiles_notification_work_idx;

alter table public.guild_profiles
    drop column if exists has_notification_work;

alter table public.guild_profiles
    add column has_notification_work boolean generated always as (
        public.idle_grow_has_pending_notification_work(data)
    ) stored;

create index guild_profiles_notification_work_idx
    on public.guild_profiles (guild_id, user_id)
    where has_notification_work;

create or replace function public.idle_grow_list_notification_candidates(
    p_guild_ids bigint[]
)
returns table (
    guild_id bigint,
    user_id bigint
)
language sql
stable
set search_path = public
as $$
    select profile.guild_id, profile.user_id
    from public.guild_profiles as profile
    where profile.has_notification_work
      and profile.guild_id = any(coalesce(p_guild_ids, '{}'::bigint[]))
    order by profile.guild_id, profile.user_id;
$$;

revoke all on function public.idle_grow_has_pending_notification_work(jsonb)
    from public, anon, authenticated;
revoke all on function public.idle_grow_list_notification_candidates(bigint[])
    from public, anon, authenticated;

grant execute on function public.idle_grow_has_pending_notification_work(jsonb)
    to service_role;
grant execute on function public.idle_grow_list_notification_candidates(bigint[])
    to service_role;

insert into public.app_schema_migrations (version)
values ('004_batched_notification_candidates')
on conflict (version) do nothing;

commit;
