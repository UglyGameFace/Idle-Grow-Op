#!/usr/bin/env python3
"""Copy legacy global Idle Grow data into one explicit home guild.

Dry-run is the default. Pass --apply only after reviewing the summary.
The legacy tables are never modified or deleted by this tool.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from typing import Any

PAGE_SIZE = 500
WRITE_BATCH_SIZE = 100


class MigrationConflict(RuntimeError):
    """Raised when scoped destination data differs from legacy source data."""


def _positive_id(value: str, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError(f"{name} must be positive")
    return number


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _fetch_all_legacy_users(client) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = (
            client.table("users")
            .select("id,data")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        page = list(response.data or [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _existing_profiles(client, guild_id: int) -> dict[int, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = (
            client.table("guild_profiles")
            .select("user_id,data")
            .eq("guild_id", guild_id)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        page = list(response.data or [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return {int(row["user_id"]): dict(row.get("data") or {}) for row in rows}


def _legacy_world(client) -> dict[str, Any] | None:
    response = client.table("world").select("data").eq("id", 1).limit(1).execute()
    if not response.data:
        return None
    return dict(response.data[0].get("data") or {})


def _existing_world(client, guild_id: int) -> dict[str, Any] | None:
    response = (
        client.table("guild_worlds")
        .select("data")
        .eq("guild_id", guild_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    return dict(response.data[0].get("data") or {})


def build_plan(client, guild_id: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int]:
    legacy_users = _fetch_all_legacy_users(client)
    existing = _existing_profiles(client, guild_id)
    profile_rows: list[dict[str, Any]] = []
    skipped = 0

    for row in legacy_users:
        user_id = int(row["id"])
        if user_id <= 0:
            raise MigrationConflict(f"legacy user id is invalid: {user_id}")
        data = dict(row.get("data") or {})
        current = existing.get(user_id)
        if current is not None:
            if current != data:
                raise MigrationConflict(
                    f"guild profile already exists with different data: guild={guild_id} user={user_id}"
                )
            skipped += 1
            continue
        profile_rows.append({"guild_id": guild_id, "user_id": user_id, "data": data})

    source_world = _legacy_world(client)
    target_world = _existing_world(client, guild_id)
    world_row: dict[str, Any] | None = None
    if source_world is not None:
        if target_world is None:
            world_row = {"guild_id": guild_id, "data": source_world}
        elif target_world != source_world:
            raise MigrationConflict(
                f"guild world already exists with different data: guild={guild_id}"
            )

    return profile_rows, world_row, skipped


def apply_plan(client, profile_rows: list[dict[str, Any]], world_row: dict[str, Any] | None) -> None:
    for batch in _chunks(profile_rows, WRITE_BATCH_SIZE):
        client.table("guild_profiles").insert(batch).execute()
    if world_row is not None:
        client.table("guild_worlds").insert(world_row).execute()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--guild-id",
        required=True,
        type=lambda value: _positive_id(value, "guild-id"),
        help="Discord guild that should receive the old global progress",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the migration; without this flag the command is dry-run only",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    url = os.environ.get("IDLE_SUPABASE_URL", "").strip()
    key = os.environ.get("IDLE_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit(
            "IDLE_SUPABASE_URL and IDLE_SUPABASE_SERVICE_ROLE_KEY are required"
        )

    from supabase import create_client

    client = create_client(url, key)
    profiles, world, skipped = build_plan(client, args.guild_id)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] home guild: {args.guild_id}")
    print(f"profiles to copy: {len(profiles)}")
    print(f"identical profiles already present: {skipped}")
    print(f"world to copy: {'yes' if world is not None else 'no'}")
    print("legacy users/world tables will remain untouched")

    if args.apply:
        apply_plan(client, profiles, world)
        print("migration applied successfully")
    else:
        print("no writes performed; rerun with --apply after reviewing this summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
