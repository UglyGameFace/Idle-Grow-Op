from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "profile_signatures.py"
source = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one anchor, found {count}: {old[:100]!r}")
    source = source.replace(old, new, 1)


replace_once(
    '''    def _lock_for(self, guild_id: int, channel_id: int) -> asyncio.Lock:
        key = (int(guild_id), int(channel_id))
        lock = self._channel_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._channel_locks[key] = lock
        return lock

    def _schedule_user_card_cleanup''',
    '''    def _lock_for(self, guild_id: int, channel_id: int) -> asyncio.Lock:
        key = (int(guild_id), int(channel_id))
        lock = self._channel_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._channel_locks[key] = lock
        return lock

    def _bump_channel_generation(self, key: tuple[int, int]) -> int:
        generation = self._channel_generation.get(key, 0) + 1
        self._channel_generation[key] = generation
        pending = self._pending.pop(key, None)
        if pending is not None and not pending.done():
            pending.cancel()
        return generation

    async def _discover_owned_signatures(
        self,
        channel: discord.TextChannel,
    ) -> list[discord.Message] | None:
        cards: list[discord.Message] = []
        try:
            async for message in channel.history(limit=SIGNATURE_HISTORY_SCAN_LIMIT):
                if self.bot.user is None or message.author.id != self.bot.user.id:
                    continue
                if not message.embeds:
                    continue
                if (message.embeds[0].footer.text or "") == SIGNATURE_MARKER:
                    cards.append(message)
        except discord.DiscordException:
            return None
        cards.sort(key=lambda message: message.id, reverse=True)
        return cards

    def _schedule_user_card_cleanup''',
)

replace_once(
    '''        key = (message.guild.id, message.channel.id)
        generation = self._channel_generation.get(key, 0) + 1
        self._channel_generation[key] = generation
        previous = self._pending.get(key)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.create_task(''',
    '''        key = (message.guild.id, message.channel.id)
        generation = self._bump_channel_generation(key)
        task = asyncio.create_task(''',
)

replace_once(
    '''            old_message = None
            old_message_id = _safe_int(state.get("message_id"))
            if old_message_id > 0:
                old_message = await self._fetch_owned_signature(channel, old_message_id)

            if (
                old_message is not None''',
    '''            old_message = None
            old_message_id = _safe_int(state.get("message_id"))
            if old_message_id > 0:
                old_message = await self._fetch_owned_signature(channel, old_message_id)
            if old_message is None:
                discovered = await self._discover_owned_signatures(channel)
                if discovered is None:
                    return
                old_message = discovered[0] if discovered else None
                for duplicate in discovered[1:]:
                    try:
                        await duplicate.delete()
                    except discord.DiscordException:
                        pass

            if (
                old_message is not None''',
)

replace_once(
    '''            await self._store_state(
                guild.id,
                channel.id,
                message_id=sent.id,
                user_id=member.id,
                fingerprint=fingerprint,
                updated_at=recorded_epoch,
            )''',
    '''            try:
                await self._store_state(
                    guild.id,
                    channel.id,
                    message_id=sent.id,
                    user_id=member.id,
                    fingerprint=fingerprint,
                    updated_at=recorded_epoch,
                )
            except Exception:
                try:
                    await sent.delete()
                except discord.DiscordException:
                    pass
                try:
                    await self._clear_state(guild.id, channel.id)
                except Exception:
                    logger.exception(
                        "Could not clear failed signature state guild=%s channel=%s",
                        guild.id,
                        channel.id,
                    )
                raise''',
)

start = source.index('    async def remove_user_cards(self, guild_id: int, user_id: int) -> None:\n')
end = source.index('    async def sync_guild_configuration(self, guild: discord.Guild) -> None:\n', start)
replacement = '''    async def remove_user_cards(self, guild_id: int, user_id: int) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return
        config = await self._get_signature_config(guild.id)
        world = await self.bot.db.get_world(guild.id)
        raw_state = world.get(SIGNATURE_STATE_KEY)
        state = dict(raw_state) if isinstance(raw_state, dict) else {}
        channel_ids = {
            _safe_int(value)
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if _safe_int(value) > 0
        }
        channel_ids.update(
            _safe_int(value) for value in state if _safe_int(value) > 0
        )

        for channel_id in channel_ids:
            key = (guild.id, channel_id)
            self._bump_channel_generation(key)
            async with self._lock_for(*key):
                current_world = await self.bot.db.get_world(guild.id)
                current_state = current_world.get(SIGNATURE_STATE_KEY)
                descriptor = (
                    current_state.get(str(channel_id), {})
                    if isinstance(current_state, dict)
                    else {}
                )
                if not isinstance(descriptor, dict):
                    continue
                if _safe_int(descriptor.get("user_id")) != int(user_id):
                    continue
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    message = await self._fetch_owned_signature(
                        channel,
                        _safe_int(descriptor.get("message_id")),
                    )
                    if message is not None:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
                await self._clear_state(guild.id, channel_id)

'''
source = source[:start] + replacement + source[end:]

start = source.index('    async def sync_guild_configuration(self, guild: discord.Guild) -> None:\n')
end = source.index('    async def invalidate_guild_cards(self, guild: discord.Guild) -> None:\n', start)
replacement = '''    async def sync_guild_configuration(self, guild: discord.Guild) -> None:
        config = await self._get_signature_config(guild.id)
        enabled = bool(config.get(SIGNATURE_ENABLED_KEY, False))
        configured_ids = {
            _safe_int(value)
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if _safe_int(value) > 0
        }
        world = await self.bot.db.get_world(guild.id)
        raw_state = world.get(SIGNATURE_STATE_KEY)
        state = dict(raw_state) if isinstance(raw_state, dict) else {}
        remove_ids = {
            _safe_int(channel_id)
            for channel_id in state
            if _safe_int(channel_id) > 0
            and (not enabled or _safe_int(channel_id) not in configured_ids)
        }
        for channel_id in remove_ids:
            key = (guild.id, channel_id)
            self._bump_channel_generation(key)
            async with self._lock_for(*key):
                current_world = await self.bot.db.get_world(guild.id)
                current_state = current_world.get(SIGNATURE_STATE_KEY)
                descriptor = (
                    current_state.get(str(channel_id), {})
                    if isinstance(current_state, dict)
                    else {}
                )
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel) and isinstance(descriptor, dict):
                    message = await self._fetch_owned_signature(
                        channel,
                        _safe_int(descriptor.get("message_id")),
                    )
                    if message is not None:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
                await self._clear_state(guild.id, channel_id)
        if enabled:
            await self.reconcile_guild(guild)

'''
source = source[:start] + replacement + source[end:]

start = source.index('    async def disable_guild(self, guild: discord.Guild) -> None:\n')
end = source.index('    async def reconcile_guild(self, guild: discord.Guild) -> None:\n', start)
replacement = '''    async def disable_guild(self, guild: discord.Guild) -> None:
        config = await self._get_signature_config(guild.id)
        world = await self.bot.db.get_world(guild.id)
        raw_state = world.get(SIGNATURE_STATE_KEY)
        state = dict(raw_state) if isinstance(raw_state, dict) else {}
        keys = {
            key for key in self._channel_generation if key[0] == guild.id
        }
        keys.update(key for key in self._pending if key[0] == guild.id)
        keys.update(
            (guild.id, _safe_int(value))
            for value in config.get(SIGNATURE_CHANNELS_KEY, [])
            if _safe_int(value) > 0
        )
        keys.update(
            (guild.id, _safe_int(value))
            for value in state
            if _safe_int(value) > 0
        )
        for key in keys:
            self._bump_channel_generation(key)

        for key in sorted(keys):
            _guild_id, channel_id = key
            async with self._lock_for(*key):
                current_world = await self.bot.db.get_world(guild.id)
                current_state = current_world.get(SIGNATURE_STATE_KEY)
                descriptor = (
                    current_state.get(str(channel_id), {})
                    if isinstance(current_state, dict)
                    else {}
                )
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel) and isinstance(descriptor, dict):
                    message = await self._fetch_owned_signature(
                        channel,
                        _safe_int(descriptor.get("message_id")),
                    )
                    if message is not None:
                        try:
                            await message.delete()
                        except discord.DiscordException:
                            pass
                await self._clear_state(guild.id, channel_id)

        async with self.bot.db.lock:
            mutable_world = await self.bot.db.get_world(guild.id)
            if SIGNATURE_STATE_KEY in mutable_world:
                mutable_world.pop(SIGNATURE_STATE_KEY, None)
                self.bot.db.mark_world_dirty(guild.id)

'''
source = source[:start] + replacement + source[end:]

replace_once(
    '''            cards = []
            try:
                async for message in channel.history(limit=SIGNATURE_HISTORY_SCAN_LIMIT):
                    if self.bot.user is None or message.author.id != self.bot.user.id:
                        continue
                    if not message.embeds:
                        continue
                    if (message.embeds[0].footer.text or "") == SIGNATURE_MARKER:
                        cards.append(message)
            except discord.DiscordException:
                continue

            cards.sort(key=lambda message: message.id, reverse=True)''',
    '''            cards = await self._discover_owned_signatures(channel)
            if cards is None:
                continue''',
)

path.write_text(source, encoding="utf-8")

contract_path = ROOT / "tests" / "test_profile_signature_contract.py"
contract = contract_path.read_text(encoding="utf-8")
anchor = '''    assert "await duplicate.delete()" in SOURCE


def test_platforms_and_privacy_use_scoped_persistence():'''
insert = '''    assert "await duplicate.delete()" in SOURCE
    assert "async def _discover_owned_signatures" in SOURCE


def test_privacy_and_configuration_changes_invalidate_in_flight_cards():
    assert "def _bump_channel_generation" in SOURCE
    assert "async with self._lock_for(*key):" in SOURCE
    assert "current_world = await self.bot.db.get_world(guild.id)" in SOURCE
    assert "await self.remove_user_cards" in SOURCE
    assert "try:\n                await self._store_state" in SOURCE
    assert "await sent.delete()" in SOURCE


def test_platforms_and_privacy_use_scoped_persistence():'''
if contract.count(anchor) != 1:
    raise RuntimeError("Could not add privacy race contract")
contract_path.write_text(contract.replace(anchor, insert, 1), encoding="utf-8")

core_path = ROOT / "tests" / "test_profile_signature_core.py"
core = core_path.read_text(encoding="utf-8")
core += '''\n\ndef test_generation_bump_cancels_only_the_pending_debounce_task():\n    import asyncio\n\n    from profile_signatures import ProfileSignatures\n\n    class BotStub:\n        guilds = []\n\n    async def scenario():\n        cog = ProfileSignatures(BotStub())\n        key = (1, 2)\n        pending = asyncio.create_task(asyncio.sleep(60))\n        cog._pending[key] = pending\n        generation = cog._bump_channel_generation(key)\n        await asyncio.sleep(0)\n        assert generation == 1\n        assert cog._channel_generation[key] == 1\n        assert key not in cog._pending\n        assert pending.cancelled()\n\n    asyncio.run(scenario())\n'''
core_path.write_text(core, encoding="utf-8")
