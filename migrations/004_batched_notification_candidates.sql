begin;

create or replace function public.idle_grow_has_pending_notification_work(
    p_data jsonb
)
returns boolean
language sql
immutable
set search_path = public
as $$
    with preferences as (
        select
            case
                when jsonb_typeof(p_data #> '{settings,notifications}') = 'boolean'
                then (p_data #>> '{settings,notifications}')::boolean
                else true
            end as enabled,
            case
                when jsonb_typeof(
                    p_data #> '{settings,notification_categories,plant_ready}'
                ) = 'boolean'
                then (
                    p_data #>> '{settings,notification_categories,plant_ready}'
                )::boolean
                else null
            end as plant_override,
            case
                when jsonb_typeof(
                    p_data #> '{settings,notification_categories,lab_ready}'
                ) = 'boolean'
                then (
                    p_data #>> '{settings,notification_categories,lab_ready}'
                )::boolean
                else null
            end as lab_override
    ),
    resolved as (
        select
            enabled,
            coalesce(plant_override, enabled) as plant_enabled,
            coalesce(lab_override, enabled) as lab_enabled
        from preferences
    )
    select
        enabled
        and (
            (
                plant_enabled
                and exists (
                    select 1
                    from jsonb_array_elements(
                        case
                            when jsonb_typeof(p_data -> 'plants') = 'array'
                            then p_data -> 'plants'
                            else '[]'::jsonb
                        end
                    ) as plant
                    where jsonb_typeof(plant) = 'object'
                      and (
                          case
                              when jsonb_typeof(plant -> 'notified') = 'boolean'
                              then (plant ->> 'notified')::boolean
                              else false
                          end
                      ) = false
                )
            )
            or (
                lab_enabled
                and exists (
                    select 1
                    from jsonb_array_elements(
                        case
                            when jsonb_typeof(p_data -> 'processing_queue') = 'array'
                            then p_data -> 'processing_queue'
                            else '[]'::jsonb
                        end
                    ) as batch
                    where jsonb_typeof(batch) = 'object'
                      and (
                          case
                              when jsonb_typeof(batch -> 'notified') = 'boolean'
                              then (batch ->> 'notified')::boolean
                              else false
                          end
                      ) = false
                )
            )
        )
    from resolved;
$$;

alter table public.guild_profiles
    add column if not exists has_pending_notification_work boolean generated always as (
        public.idle_grow_has_pending_notification_work(data)
    ) stored;

create index if not exists guild_profiles_pending_notification_work_idx
    on public.guild_profiles (guild_id, user_id)
    where has_pending_notification_work;

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
    where profile.has_pending_notification_work
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
