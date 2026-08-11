import asyncio
import pytest

from app.workflows.thread_workflow import (
    _InFlightToolCallCoordinator,
    canonical_tool_call_key,
)


def test_canonical_tool_call_key_ignores_json_object_order():
    assert canonical_tool_call_key(" Lookup ", '{"b": 2, "a": 1}') == canonical_tool_call_key(
        "lookup", '{"a":1,"b":2}'
    )


def test_canonical_tool_call_key_includes_changed_arguments():
    assert canonical_tool_call_key("lookup", '{"page": 1}') != canonical_tool_call_key(
        "lookup", '{"page": 2}'
    )


def test_same_key_concurrently_executes_once_and_caches_failure():
    async def scenario():
        coordinator = _InFlightToolCallCoordinator()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def operation():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            raise RuntimeError("upstream unavailable")

        first = asyncio.create_task(coordinator.run(("lookup", '{"a":1}'), operation))
        await started.wait()
        second = asyncio.create_task(
            coordinator.run(("lookup", '{"a":1}'), operation)
        )
        await asyncio.sleep(0)
        release.set()
        first_result, second_result = await asyncio.gather(first, second)
        cached_result = await coordinator.run(("lookup", '{"a":1}'), operation)

        assert calls == 1
        assert first_result == "Error executing tool: upstream unavailable"
        assert second_result.startswith("[DUPLICATE TOOL CALL SUPPRESSED]")
        assert "upstream unavailable" in second_result
        assert cached_result == second_result

    asyncio.run(scenario())


def test_different_keys_can_execute_concurrently():
    async def scenario():
        coordinator = _InFlightToolCallCoordinator()
        started = {"a": asyncio.Event(), "b": asyncio.Event()}
        release = asyncio.Event()
        calls = []

        async def operation(name):
            calls.append(name)
            started[name].set()
            await release.wait()
            return name

        first = asyncio.create_task(
            coordinator.run(("lookup", '{"key":"a"}'), lambda: operation("a"))
        )
        second = asyncio.create_task(
            coordinator.run(("lookup", '{"key":"b"}'), lambda: operation("b"))
        )
        await asyncio.gather(started["a"].wait(), started["b"].wait())
        assert calls == ["a", "b"]
        release.set()
        assert await asyncio.gather(first, second) == ["a", "b"]

    asyncio.run(scenario())


def test_unexpected_base_exception_unblocks_duplicate_waiter():
    class Unexpected(BaseException):
        pass

    async def scenario():
        coordinator = _InFlightToolCallCoordinator()
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation():
            started.set()
            await release.wait()
            raise Unexpected("broken")

        owner = asyncio.create_task(coordinator.run(("lookup", "{}"), operation))
        await started.wait()
        waiter = asyncio.create_task(coordinator.run(("lookup", "{}"), operation))
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(Unexpected):
            await owner
        with pytest.raises(Unexpected):
            await waiter

    asyncio.run(scenario())
