begin;

alter table public.guild_profiles
    add column if not exists casino_total_profit bigint generated always as (
        coalesce((data #>> '{stats,casino_total_profit}')::bigint, 0)
    ) stored,
    add column if not exists coinflip_profit bigint generated always as (
        coalesce((data #>> '{stats,coinflip_profit}')::bigint, 0)
    ) stored,
    add column if not exists slots_profit bigint generated always as (
        coalesce((data #>> '{stats,slots_profit}')::bigint, 0)
    ) stored,
    add column if not exists blackjack_profit bigint generated always as (
        coalesce((data #>> '{stats,blackjack_profit}')::bigint, 0)
    ) stored,
    add column if not exists dice_profit bigint generated always as (
        coalesce((data #>> '{stats,dice_profit}')::bigint, 0)
    ) stored,
    add column if not exists roulette_profit bigint generated always as (
        coalesce((data #>> '{stats,roulette_profit}')::bigint, 0)
    ) stored,
    add column if not exists hilo_profit bigint generated always as (
        coalesce((data #>> '{stats,hilo_profit}')::bigint, 0)
    ) stored,
    add column if not exists rps_profit bigint generated always as (
        coalesce((data #>> '{stats,rps_profit}')::bigint, 0)
    ) stored,
    add column if not exists crash_profit bigint generated always as (
        coalesce((data #>> '{stats,crash_profit}')::bigint, 0)
    ) stored,
    add column if not exists wheel_profit bigint generated always as (
        coalesce((data #>> '{stats,wheel_profit}')::bigint, 0)
    ) stored,
    add column if not exists cups_profit bigint generated always as (
        coalesce((data #>> '{stats,cups_profit}')::bigint, 0)
    ) stored,
    add column if not exists keno_profit bigint generated always as (
        coalesce((data #>> '{stats,keno_profit}')::bigint, 0)
    ) stored;

create index if not exists guild_profiles_guild_casino_total_profit_idx
    on public.guild_profiles (guild_id, casino_total_profit desc, user_id);
create index if not exists guild_profiles_guild_coinflip_profit_idx
    on public.guild_profiles (guild_id, coinflip_profit desc, user_id);
create index if not exists guild_profiles_guild_slots_profit_idx
    on public.guild_profiles (guild_id, slots_profit desc, user_id);
create index if not exists guild_profiles_guild_blackjack_profit_idx
    on public.guild_profiles (guild_id, blackjack_profit desc, user_id);
create index if not exists guild_profiles_guild_dice_profit_idx
    on public.guild_profiles (guild_id, dice_profit desc, user_id);
create index if not exists guild_profiles_guild_roulette_profit_idx
    on public.guild_profiles (guild_id, roulette_profit desc, user_id);
create index if not exists guild_profiles_guild_hilo_profit_idx
    on public.guild_profiles (guild_id, hilo_profit desc, user_id);
create index if not exists guild_profiles_guild_rps_profit_idx
    on public.guild_profiles (guild_id, rps_profit desc, user_id);
create index if not exists guild_profiles_guild_crash_profit_idx
    on public.guild_profiles (guild_id, crash_profit desc, user_id);
create index if not exists guild_profiles_guild_wheel_profit_idx
    on public.guild_profiles (guild_id, wheel_profit desc, user_id);
create index if not exists guild_profiles_guild_cups_profit_idx
    on public.guild_profiles (guild_id, cups_profit desc, user_id);
create index if not exists guild_profiles_guild_keno_profit_idx
    on public.guild_profiles (guild_id, keno_profit desc, user_id);

insert into public.app_schema_migrations (version)
values ('002_enterprise_casino_metrics')
on conflict (version) do nothing;

commit;
