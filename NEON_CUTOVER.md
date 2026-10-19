# Idle Grow Op: Neon cutover checklist

## Current status
- Destination: Neon Free project "idle-grow-op", PostgreSQL 17, database "idle_grow_op".
- The four app migrations are installed and verified. All scoped records were copied.
- Independent source/target count, JSON-byte, key and timestamp digests matched:
  3 global accounts, 42 guild profiles, 3 guild worlds.
- Keep original Supabase records intact during rollback window.
- No Discloud changes occur when the adapter PR is merged.

## Discloud configuration
Store the *direct* Neon PostgreSQL connection string as an environment secret
named \`IDLE_NEON_DATABASE_URL\`. Use the connection string from the Neon
Console's Connect screen for database \`idle_grow_op\`, with TLS required.
**Never commit or paste that password into GitHub.**

When ready for cutover, set \`IDLE_PERSISTENCE_BACKEND=neon\` on the Idle Grow
Discloud app. When omitted the existing Supabase backend remains selected.
If Neon startup fails, the bot refuses to start; it never writes to a stale
Supabase fallback. The old secrets may be retained temporarily for rollback.

## Before starting the bot
1. Stop any active Idle Grow process or write job on the old database.
2. Recheck source and Neon row counts and per-table data digests. If the
   source changed after the snapshot, reconcile its newer rows safely first.
3. Verify both required PostgreSQL functions and all generated columns.
4. Confirm database credentials are only configured on Idle Grow (not Dank Shield).

## Acceptance / rollback
1. Observe a successful schema check, PostgreSQL connection and Discord login.
2. Exercise one persistent change, restart the bot and check the saved value
   remains in Neon. Check new gameplay in its selected world mode.
3. Confirm indexed casino/guild leaderboards, notification candidates,
   atomic profile+world saves and successful graceful shutdown.
4. Continue the existing Phase 11 /game, Grow, Shop and other live acceptance.
5. Rollback only after stopping all writers and reconciling records modified
   on Neon, never by switching to a stale database while the bot is running.
