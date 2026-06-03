from datetime import timedelta

from temporalio.workflow import defn, execute_activity, run


@defn
class IndexDiscordThreadWorkflow:
    """Import Discord thread history into the linked ThreadBot thread."""

    @run
    async def run(self, input: dict) -> dict:
        return await execute_activity(
            "index_discord_thread_history",
            input,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(seconds=30),
            summary="Index Discord thread history",
        )
