import asyncio
from types import SimpleNamespace

from profile_signatures import ProfileSignatures
from sesh import Sesh
from tasks import Tasks


def test_scheduled_loop_callbacks_contain_unexpected_iteration_failures():
    async def scenario():
        cog = Tasks(SimpleNamespace())

        async def boom():
            raise RuntimeError("simulated scheduled failure")

        cog._game_cycle_once = boom
        cog._notification_check_once = boom
        cog._status_cycle_once = boom

        await Tasks.game_cycle.coro(cog)
        await Tasks.notification_check.coro(cog)
        await Tasks.status_cycle.coro(cog)

    asyncio.run(scenario())


def test_profile_signature_cleanup_tasks_are_owned_and_cancelled_on_unload():
    async def scenario():
        cog = ProfileSignatures(SimpleNamespace(guilds=[]))
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked_cleanup(guild_id, user_id):
            started.set()
            await release.wait()

        cog.remove_user_cards = blocked_cleanup
        cog._schedule_user_card_cleanup(42, guild_id=123)
        await started.wait()

        assert len(cog._cleanup_tasks) == 1
        task = next(iter(cog._cleanup_tasks))
        cog.cog_unload()
        await asyncio.gather(task, return_exceptions=True)

        assert task.cancelled()
        assert not cog._cleanup_tasks

    asyncio.run(scenario())


def test_private_sesh_cleanup_contains_detached_task_failures():
    async def scenario():
        bot = SimpleNamespace(get_guild=lambda _guild_id: None)
        cog = Sesh(bot)
        key = (123, 456)
        cog._sesh_sessions[key] = object()

        async def fail_end(_key, *, reason):
            raise RuntimeError("simulated cleanup failure")

        cog._end_sesh_session = fail_end

        await cog._private_room_cleanup(key, 456, 0)

    asyncio.run(scenario())
