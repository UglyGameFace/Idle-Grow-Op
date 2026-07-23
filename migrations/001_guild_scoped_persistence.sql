begin;

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
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (guild_id, user_id),
    constraint guild_profiles_guild_id_positive check (guild_id > 0),
    constraint guild_profiles_user_id_positive check (user_id > 0)
);

create index if not exists guild_profiles_user_id_idx
    on public.guild_profiles (user_id);

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

commit;
