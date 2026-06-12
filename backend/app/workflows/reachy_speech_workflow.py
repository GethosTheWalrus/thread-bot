from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import defn, execute_activity, init, run, signal


@defn
class ReachySpeechWorkflow:
    """Incremental speech sink for a single Reachy response.

    The parent ThreadBot workflow signals token chunks here. This workflow runs
    on the local Reachy task queue and turns complete phrases into local speech
    activities, so speech can begin before the final LLM response is complete.
    """

    @init
    def __init__(self, input: dict) -> None:
        self._chunks: list[str] = []
        self._done = False

    @signal
    async def add_text(self, text: str) -> None:
        if text:
            self._chunks.append(text)

    @signal
    async def finish(self) -> None:
        self._done = True

    def _take_speakable(self, pending: str, *, force: bool = False) -> tuple[str, str]:
        if not pending:
            return "", ""
        if force:
            return pending.strip(), ""
        if len(pending) < 80:
            return "", pending

        split_at = -1
        for idx, char in enumerate(pending):
            if char in ".!?\n" and idx >= 40:
                split_at = idx + 1
        if split_at < 0 and len(pending) >= 220:
            split_at = pending.rfind(" ", 0, 220)
        if split_at <= 0:
            return "", pending
        return pending[:split_at].strip(), pending[split_at:].lstrip()

    @run
    async def run(self, input: dict) -> dict:
        with workflow.unsafe.imports_passed_through():
            from app.activities.reachy_activities import speak_reachy_text

        pending = ""
        spoken_chunks = 0
        llm_config = input.get("llm_config") or {}
        reachy_config = input.get("reachy") or {}

        while not self._done or self._chunks or pending.strip():
            await workflow.wait_condition(lambda: self._done or bool(self._chunks))
            if self._chunks:
                pending += "".join(self._chunks)
                self._chunks.clear()

            text, pending = self._take_speakable(pending, force=self._done and not self._chunks)
            if not text:
                continue

            try:
                await execute_activity(
                    speak_reachy_text,
                    {"text": text, "llm_config": llm_config, "reachy": reachy_config},
                    start_to_close_timeout=timedelta(seconds=180),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    summary="Speak Reachy response chunk",
                )
            except Exception:
                # Speech is a side effect; a robot/audio failure should not fail
                # the ThreadBot response that already streamed to the user.
                pass
            spoken_chunks += 1

        return {"spoken_chunks": spoken_chunks}
