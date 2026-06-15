from __future__ import annotations

import asyncio
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
        self._flush_requested = False
        self._thinking_active = bool((input or {}).get("start_thinking"))

    @signal
    async def add_text(self, text: str) -> None:
        if text:
            self._chunks.append(text)
            self._thinking_active = False

    @signal
    async def flush(self) -> None:
        self._flush_requested = True

    @signal
    async def start_thinking(self) -> None:
        self._thinking_active = True

    @signal
    async def stop_thinking(self) -> None:
        self._thinking_active = False

    @signal
    async def finish(self) -> None:
        self._done = True
        self._thinking_active = False
        self._flush_requested = True

    def _take_speakable(self, pending: str, *, force: bool = False) -> tuple[str, str]:
        if not pending:
            return "", ""
        if force:
            text = pending[:700].strip()
            return text, pending[700:].lstrip()

        split_at = -1
        scan_limit = min(len(pending), 320)
        for idx, char in enumerate(pending[:scan_limit]):
            if char in ".!?\n" and idx >= 24:
                split_at = idx + 1
        if split_at < 0 and len(pending) < 80:
            return "", pending
        if split_at < 0 and len(pending) >= 220:
            split_at = pending.rfind(" ", 0, 220)
        if split_at < 0 and len(pending) >= 700:
            split_at = 700
        if split_at <= 0:
            return "", pending
        return pending[:split_at].strip(), pending[split_at:].lstrip()

    @run
    async def run(self, input: dict) -> dict:
        with workflow.unsafe.imports_passed_through():
            from app.activities.reachy_activities import play_reachy_animation, play_reachy_mood, set_reachy_volume, speak_reachy_text

        pending = ""
        spoken_chunks = 0
        played_response_mood = False
        llm_config = input.get("llm_config") or {}
        reachy_config = input.get("reachy") or {}
        post_speech_sleep_delay = float(reachy_config.get("post_speech_sleep_delay") or 2.0)
        output_volume = int(reachy_config.get("output_volume") or 100)
        response_mood = str(reachy_config.get("response_mood") or "helpful")

        try:
            await execute_activity(
                set_reachy_volume,
                {"volume": output_volume, "reachy": reachy_config},
                start_to_close_timeout=timedelta(seconds=10),
                heartbeat_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
                summary="Set Reachy output volume",
            )
        except Exception:
            workflow.logger.exception("Reachy volume setup failed")

        try:
            await execute_activity(
                play_reachy_animation,
                {"name": "wake", "duration": 1.0, "reachy": reachy_config},
                start_to_close_timeout=timedelta(seconds=20),
                heartbeat_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
                summary="Wake Reachy for speech turn",
            )
        except Exception:
            workflow.logger.exception("Reachy wake failed")

        while not self._done or self._chunks or pending.strip():
            if not self._chunks and not pending.strip():
                if self._thinking_active:
                    try:
                        await execute_activity(
                            play_reachy_mood,
                            {"mood": "thoughtful", "reachy": reachy_config},
                            start_to_close_timeout=timedelta(seconds=20),
                            heartbeat_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            summary="Play Reachy thinking persona",
                        )
                    except Exception:
                        workflow.logger.exception("Reachy thinking persona failed")
                    continue

                # Idle wait — give the workflow a chance to receive more
                # text. We use a longer wait here (60s) and rely on
                # signals (`add_text`, `finish`, `start_thinking`) to wake
                # the workflow early. This avoids the tight 2s poll loop
                # that previously tripped the Temporal deadlock detector
                # on a fast inner loop.
                try:
                    await workflow.wait_condition(
                        lambda: self._done or bool(self._chunks) or self._thinking_active,
                        timeout=timedelta(seconds=60),
                        timeout_summary="Wait for Reachy speech text",
                    )
                except asyncio.TimeoutError:
                    pass
                # Always re-enter the while loop's top condition check;
                # `wait_condition` has already yielded, so we're not at
                # risk of the deadlock detector.
            if self._chunks:
                pending += "".join(self._chunks)
                self._chunks.clear()

            force = self._flush_requested or (self._done and not self._chunks)
            text, pending = self._take_speakable(pending, force=force)
            self._flush_requested = False
            if not text:
                try:
                    await workflow.wait_condition(
                        lambda: self._done or self._flush_requested or bool(self._chunks),
                        timeout=timedelta(seconds=2),
                        timeout_summary="Wait for more Reachy speech text",
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            if not played_response_mood:
                played_response_mood = True
                try:
                    await execute_activity(
                        play_reachy_mood,
                        {"mood": response_mood, "reachy": reachy_config},
                        start_to_close_timeout=timedelta(seconds=20),
                        heartbeat_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        summary="Play Reachy response mood persona",
                    )
                except Exception:
                    workflow.logger.exception("Reachy response mood persona failed")

            try:
                result = await execute_activity(
                    speak_reachy_text,
                    {"text": text, "llm_config": llm_config, "reachy": reachy_config},
                    start_to_close_timeout=timedelta(seconds=180),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    summary="Speak Reachy response chunk",
                )
                if isinstance(result, dict) and not result.get("spoken"):
                    workflow.logger.warning("Reachy speech chunk was not spoken: %s", result.get("error") or result)
            except Exception:
                # Speech is a side effect; a robot/audio failure should not fail
                # the ThreadBot response that already streamed to the user.
                workflow.logger.exception("Reachy speech chunk failed")
                pass
            spoken_chunks += 1

        if post_speech_sleep_delay > 0:
            await workflow.sleep(timedelta(seconds=post_speech_sleep_delay))
        try:
            await execute_activity(
                play_reachy_animation,
                {"name": "sleep", "duration": 1.0, "reachy": reachy_config},
                start_to_close_timeout=timedelta(seconds=20),
                heartbeat_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
                summary="Sleep Reachy after speech turn",
            )
        except Exception:
            workflow.logger.exception("Reachy sleep failed")

        return {"spoken_chunks": spoken_chunks}
