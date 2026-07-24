begin;

create table if not exists public.app_schema_migrations (
    version text primary key,
    applied_at timestamptz not null default now()
);

create table if not exists public.global_accounts (
    user_id bigint primary key,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint global_accounts_user_id_positive check (user_id > 0)
);

create table if not exists public.guild_profiles (
    guild_id bigint not null,
    user_id bigint not null,
    data jsonb not null default '{}'::jsonb,
    balance bigint generated always as (
        greatest(0, coalesce((data ->> 'grams')::bigint, 0))
    ) stored,
    heist_wins bigint generated always as (
        greatest(0, coalesce((data #>> '{stats,heists_won}')::bigint, 0))
    ) stored,
    has_notification_work boolean generated always as (
        (
            case
                when jsonb_typeof(data -> 'plants') = 'array'
                then jsonb_array_length(data -> 'plants')
                else 0
            end
            +
            case
                when jsonb_typeof(data -> 'processing_queue') = 'array'
                then jsonb_array_length(data -> 'processing_queue')
                else 0
            end
        ) > 0
        and coalesce((data #>> '{settings,notifications}')::boolean, true)
    ) stored,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (guild_id, user_id),
    constraint guild_profiles_guild_id_positive check (guild_id > 0),
    constraint guild_profiles_user_id_positive check (user_id > 0)
);

alter table public.guild_profiles
    add column if not exists balance bigint generated always as (
        greatest(0, coalesce((data ->> 'grams')::bigint, 0))
    ) stored;

alter table public.guild_profiles
    add column if not exists heist_wins bigint generated always as (
        greatest(0, coalesce((data #>> '{stats,heists_won}')::bigint, 0))
    ) stored;

alter table public.guild_profiles
    add column if not exists has_notification_work boolean generated always as (
        (
            case
                when jsonb_typeof(data -> 'plants') = 'array'
                then jsonb_array_length(data -> 'plants')
                else 0
            end
            +
            case
                when jsonb_typeof(data -> 'processing_queue') = 'array'
                then jsonb_array_length(data -> 'processing_queue')
                else 0
            end
        ) > 0
        and coalesce((data #>> '{settings,notifications}')::boolean, true)
    ) stored;

create index if not exists guild_profiles_user_id_idx
    on public.guild_profiles (user_id);

create index if not exists guild_profiles_guild_balance_idx
    on public.guild_profiles (guild_id, balance desc, user_id);

create index if not exists guild_profiles_guild_heist_wins_idx
    on public.guild_profiles (guild_id, heist_wins desc, user_id);

create index if not exists guild_profiles_notification_work_idx
    on public.guild_profiles (guild_id, user_id)
    where has_notification_work;

create table if not exists public.guild_worlds (
    guild_id bigint primary key,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint guild_worlds_guild_id_positive check (guild_id > 0)
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists global_accounts_set_updated_at on public.global_accounts;
create trigger global_accounts_set_updated_at
before update on public.global_accounts
for each row execute function public.set_updated_at();

drop trigger if exists guild_profiles_set_updated_at on public.guild_profiles;
create trigger guild_profiles_set_updated_at
before update on public.guild_profiles
for each row execute function public.set_updated_at();

drop trigger if exists guild_worlds_set_updated_at on public.guild_worlds;
create trigger guild_worlds_set_updated_at
before update on public.guild_worlds
for each row execute function public.set_updated_at();

alter table public.app_schema_migrations enable row level security;
alter table public.global_accounts enable row level security;
alter table public.guild_profiles enable row level security;
alter table public.guild_worlds enable row level security;

revoke all on table public.app_schema_migrations from anon, authenticated;
revoke all on table public.global_accounts from anon, authenticated;
revoke all on table public.guild_profiles from anon, authenticated;
revoke all on table public.guild_worlds from anon, authenticated;

grant all on table public.app_schema_migrations to service_role;
grant all on table public.global_accounts to service_role;
grant all on table public.guild_profiles to service_role;
grant all on table public.guild_worlds to service_role;

insert into public.app_schema_migrations (version)
values ('001_guild_scoped_persistence')
on conflict (version) do nothing;

commit;
