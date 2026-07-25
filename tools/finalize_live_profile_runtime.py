from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "profile_signatures.py"
source = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one anchor, found {count}: {old[:80]!r}")
    source = source.replace(old, new, 1)


replace_once(
    '''def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_platform_url''',
    '''def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_display(value: Any, *, limit: int = 100) -> str:
    text = discord.utils.escape_mentions(str(value))
    text = discord.utils.escape_markdown(text)
    return text[:limit]


def normalize_platform_url''',
)

replace_once(
    '''        self._pending: dict[tuple[int, int], asyncio.Task] = {}
        self._channel_locks: dict[tuple[int, int], asyncio.Lock] = {}''',
    '''        self._pending: dict[tuple[int, int], asyncio.Task] = {}
        self._channel_generation: dict[tuple[int, int], int] = {}
        self._channel_locks: dict[tuple[int, int], asyncio.Lock] = {}''',
)

replace_once(
    '''        self._pending.clear()

    def _lock_for''',
    '''        self._pending.clear()
        self._channel_generation.clear()

    def _lock_for''',
)

replace_once(
    '''            platforms = identity.setdefault("platforms", {})
            platforms[str(key)] = dict(entry)
            self.bot.db.mark_account_dirty(int(user_id))''',
    '''            platforms = identity.setdefault("platforms", {})
            platforms[str(key)] = dict(entry)
            if entry.get("shared", False):
                privacy = account.setdefault(GLOBAL_PRIVACY_KEY, {})
                visible = {
                    str(value)
                    for value in privacy.get("visible_fields", DEFAULT_VISIBLE_FIELDS)
                    if str(value) in FIELD_LABELS
                }
                visible.add("platforms")
                privacy["visible_fields"] = sorted(visible)
            self.bot.db.mark_account_dirty(int(user_id))''',
)

replace_once(
    '''                lines.append(f"{emoji} **{label}:** `{username}` — {state}{link_state}")''',
    '''                safe_label = _safe_display(label, limit=30)
                safe_username = _safe_display(username, limit=80)
                lines.append(
                    f"{emoji} **{safe_label}:** `{safe_username}` — {state}{link_state}"
                )''',
)

replace_once(
    '''                    f"{entry['emoji']} **{entry['label']}:** `{entry['username']}`"
                    for entry in platforms''',
    '''                    f"{entry['emoji']} **{_safe_display(entry['label'], limit=30)}:** "
                    f"`{_safe_display(entry['username'], limit=80)}`"
                    for entry in platforms''',
)

replace_once(
    '''                lines.append(f"🧢 **Crew:** {crew}")''',
    '''                lines.append(f"🧢 **Crew:** {_safe_display(crew, limit=80)}")''',
)

replace_once(
    '''        if platforms:
            lines.append(
                "🎮 "
                + " • ".join(
                    f"**{entry['label']}:** `{entry['username']}`"
                    for entry in platforms[:6]
                )
            )''',
    '''        if platforms:
            lines.append(
                " • ".join(
                    f"{entry['emoji']} **{_safe_display(entry['label'], limit=30)}:** "
                    f"`{_safe_display(entry['username'], limit=80)}`"
                    for entry in platforms[:6]
                )
            )''',
)

replace_once(
    '''        key = (message.guild.id, message.channel.id)
        previous = self._pending.get(key)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.create_task(
            self._debounced_refresh(message),''',
    '''        key = (message.guild.id, message.channel.id)
        generation = self._channel_generation.get(key, 0) + 1
        self._channel_generation[key] = generation
        previous = self._pending.get(key)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.create_task(
            self._debounced_refresh(message, generation),''',
)

replace_once(
    '''    async def _debounced_refresh(self, message: discord.Message) -> None:
        key = (message.guild.id, message.channel.id)
        task = asyncio.current_task()
        try:
            await asyncio.sleep(SIGNATURE_DEBOUNCE_SECONDS)
            if self._pending.get(key) is task:
                self._pending.pop(key, None)
            await self._refresh_signature(message)''',
    '''    async def _debounced_refresh(
        self,
        message: discord.Message,
        generation: int,
    ) -> None:
        key = (message.guild.id, message.channel.id)
        task = asyncio.current_task()
        try:
            await asyncio.sleep(SIGNATURE_DEBOUNCE_SECONDS)
            if self._channel_generation.get(key) != generation:
                return
            if self._pending.get(key) is task:
                self._pending.pop(key, None)
            await self._refresh_signature(message, generation)''',
)

replace_once(
    '''    async def _refresh_signature(self, trigger: discord.Message) -> None:
        guild = trigger.guild''',
    '''    async def _refresh_signature(
        self,
        trigger: discord.Message,
        generation: int,
    ) -> None:
        guild = trigger.guild''',
)

replace_once(
    '''        key = (guild.id, channel.id)
        async with self._lock_for(*key):
            config = await self._get_signature_config(guild.id)''',
    '''        key = (guild.id, channel.id)
        async with self._lock_for(*key):
            if self._channel_generation.get(key) != generation:
                return
            config = await self._get_signature_config(guild.id)''',
)

replace_once(
    '''            if delay:
                await asyncio.sleep(delay)

            if old_message is not None:''',
    '''            if delay:
                await asyncio.sleep(delay)
            if self._channel_generation.get(key) != generation:
                return

            if old_message is not None:''',
)

replace_once(
    '''        for key, task in list(self._pending.items()):
            if key[0] == guild.id:
                task.cancel()
                self._pending.pop(key, None)
        world = await self.bot.db.get_world(guild.id)''',
    '''        for key, task in list(self._pending.items()):
            if key[0] == guild.id:
                task.cancel()
                self._pending.pop(key, None)
        for key in list(self._channel_generation):
            if key[0] == guild.id:
                self._channel_generation.pop(key, None)
        world = await self.bot.db.get_world(guild.id)''',
)

path.write_text(source, encoding="utf-8")

contract_path = ROOT / "tests" / "test_profile_signature_contract.py"
contract = contract_path.read_text(encoding="utf-8")
old = '''    assert "if self._pending.get(key) is task:" in SOURCE
    assert "self._pending.pop(key, None)" in SOURCE
    assert "SIGNATURE_CHANNEL_COOLDOWN_SECONDS" in SOURCE'''
new = '''    assert "if self._pending.get(key) is task:" in SOURCE
    assert "self._pending.pop(key, None)" in SOURCE
    assert "self._channel_generation.get(key) != generation" in SOURCE
    assert "self._debounced_refresh(message, generation)" in SOURCE
    assert "SIGNATURE_CHANNEL_COOLDOWN_SECONDS" in SOURCE'''
if contract.count(old) != 1:
    raise RuntimeError("Could not update generation contract")
contract_path.write_text(contract.replace(old, new, 1), encoding="utf-8")

core_path = ROOT / "tests" / "test_profile_signature_core.py"
core = core_path.read_text(encoding="utf-8")
core += '''\n\ndef test_explicit_platform_sharing_enables_platform_visibility_in_source():\n    source = (Path(__file__).resolve().parents[1] / "profile_signatures.py").read_text(\n        encoding="utf-8"\n    )\n    assert 'if entry.get("shared", False):' in source\n    assert 'visible.add("platforms")' in source\n    assert "_safe_display(entry['username'], limit=80)" in source\n'''
core = core.replace("import pytest\n", "from pathlib import Path\n\nimport pytest\n", 1)
core_path.write_text(core, encoding="utf-8")
