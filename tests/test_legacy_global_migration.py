import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "legacy_migration", ROOT / "tools" / "migrate_legacy_global_data.py"
)
legacy_migration = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(legacy_migration)


class Response:
    def __init__(self, data):
        self.data = deepcopy(data)


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = {}
        self.start = 0
        self.end = None
        self.payload = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def range(self, start, end):
        self.start = start
        self.end = end
        return self

    def limit(self, amount):
        self.start = 0
        self.end = amount - 1
        return self

    def insert(self, payload):
        self.payload = deepcopy(payload)
        return self

    def execute(self):
        if self.payload is not None:
            self.client.inserts.append((self.table, self.payload))
            return Response(self.payload if isinstance(self.payload, list) else [self.payload])

        rows = deepcopy(self.client.tables.get(self.table, []))
        for column, value in self.filters.items():
            rows = [row for row in rows if row.get(column) == value]
        if self.end is not None:
            rows = rows[self.start : self.end + 1]
        return Response(rows)


class FakeClient:
    def __init__(self, tables=None):
        self.tables = deepcopy(tables or {})
        self.inserts = []

    def table(self, name):
        return Query(self, name)


def test_build_plan_copies_legacy_rows_into_explicit_guild_without_writing():
    client = FakeClient(
        {
            "users": [
                {"id": "10", "data": {"grams": 500}},
                {"id": "20", "data": {"grams": 900}},
            ],
            "world": [{"id": 1, "data": {"weather": "Sunny"}}],
            "guild_profiles": [],
            "guild_worlds": [],
        }
    )

    profiles, world, skipped = legacy_migration.build_plan(client, 123)

    assert profiles == [
        {"guild_id": 123, "user_id": 10, "data": {"grams": 500}},
        {"guild_id": 123, "user_id": 20, "data": {"grams": 900}},
    ]
    assert world == {"guild_id": 123, "data": {"weather": "Sunny"}}
    assert skipped == 0
    assert client.inserts == []


def test_build_plan_skips_identical_scoped_records_for_safe_reruns():
    client = FakeClient(
        {
            "users": [{"id": "10", "data": {"grams": 500}}],
            "world": [{"id": 1, "data": {"weather": "Sunny"}}],
            "guild_profiles": [
                {"guild_id": 123, "user_id": 10, "data": {"grams": 500}}
            ],
            "guild_worlds": [
                {"guild_id": 123, "data": {"weather": "Sunny"}}
            ],
        }
    )

    profiles, world, skipped = legacy_migration.build_plan(client, 123)

    assert profiles == []
    assert world is None
    assert skipped == 1


def test_build_plan_refuses_to_overwrite_different_scoped_profile():
    client = FakeClient(
        {
            "users": [{"id": "10", "data": {"grams": 500}}],
            "guild_profiles": [
                {"guild_id": 123, "user_id": 10, "data": {"grams": 999}}
            ],
            "world": [],
            "guild_worlds": [],
        }
    )

    with pytest.raises(legacy_migration.MigrationConflict, match="different data"):
        legacy_migration.build_plan(client, 123)


def test_apply_plan_writes_only_new_scoped_tables_and_never_legacy_tables():
    client = FakeClient()
    profiles = [
        {"guild_id": 123, "user_id": index, "data": {"grams": index}}
        for index in range(1, 206)
    ]
    world = {"guild_id": 123, "data": {"weather": "Sunny"}}

    legacy_migration.apply_plan(client, profiles, world)

    assert [table for table, _payload in client.inserts] == [
        "guild_profiles",
        "guild_profiles",
        "guild_profiles",
        "guild_worlds",
    ]
    assert all(table not in {"users", "world"} for table, _ in client.inserts)
