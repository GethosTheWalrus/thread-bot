from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import defn, execute_activity, init, run, signal


@defn
class ReachySpeechWorkflow:
    """Single-shot speech sink for one Reachy response.

    The parent ThreadBot workflow signals token deltas to ``add_text``. The
    child buffers all of them into a single response string. When the parent
    signals ``finish``, the workflow hands the full text to one
    ``synthesize_and_speak_reachy_text`` activity that runs TTS for the whole
    response, concatenates the audio, and plays it through a single Reachy
    audio session. This avoids the per-chunk TTS round-trip, per-chunk
    activity dispatch, and ``start_playing``/``stop_playing`` per chunk that
    used to leave multi-second gaps between spoken pieces.

    The child still plays the response mood once and runs a single ``talking``
    persona loop for the entire combined playback, so the robot looks alive
    while speaking.
    """

    @init
    def __init__(self, input: dict) -> None:
        self._buffered: list[str] = []
        self._done = False
        self._thinking_active = bool((input or {}).get("start_thinking"))
        self._spoke = False
        self._flush_now = False

    @signal
    async def add_text(self, text: str) -> None:
        if text:
            self._buffered.append(text)
            self._thinking_active = False

    @signal
    async def start_thinking(self) -> None:
        self._thinking_active = True

    @signal
    async def stop_thinking(self) -> None:
        self._thinking_active = False

    @signal
    async def flush(self) -> None:
        self._flush_now = True

    @signal
    async def finish(self) -> None:
        self._done = True
        self._thinking_active = False

    def _drain(self) -> str:
        if not self._buffered:
            return ""
        joined = "".join(self._buffered)
        self._buffered = []
        return joined

    @run
    async def run(self, input: dict) -> dict:
        with workflow.unsafe.imports_passed_through():
            from app.activities.reachy_activities import (
                play_reachy_animation,
                play_reachy_mood,
                set_reachy_volume,
                synthesize_and_speak_reachy_text,
            )

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

        async def _speak(text: str, *, mood: str | None) -> None:
            text = (text or "").strip()
            if not text:
                return
            if mood and not self._spoke:
                try:
                    await execute_activity(
                        play_reachy_mood,
                        {"mood": mood, "reachy": reachy_config},
                        start_to_close_timeout=timedelta(seconds=20),
                        heartbeat_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        summary="Play Reachy response mood persona",
                    )
                except Exception:
                    workflow.logger.exception("Reachy response mood persona failed")
            try:
                result = await execute_activity(
                    synthesize_and_speak_reachy_text,
                    {"texts": [text], "silence_between_seconds": 0.0, "llm_config": llm_config, "reachy": reachy_config},
                    start_to_close_timeout=timedelta(seconds=600),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    summary="Synthesize and speak Reachy response segment",
                )
                if isinstance(result, dict) and not result.get("spoken"):
                    workflow.logger.warning("Reachy segment was not spoken: %s", result.get("error") or result)
                else:
                    self._spoke = True
            except Exception:
                workflow.logger.exception("Reachy segment speech failed")

        while not self._done or self._buffered or self._flush_now:
            # Yield up front so signal deliveries and the activity result
            # can drain into the workflow state before we re-evaluate
            # conditions. This prevents a 2s+ replay loop where multiple
            # wait_condition() calls back-to-back return immediately
            # without giving the deadlock detector room to reset.
            try:
                await workflow.wait_condition(
                    lambda: True,
                    timeout=timedelta(milliseconds=1),
                    timeout_summary="Yield before re-evaluating Reachy speech loop",
                )
            except asyncio.TimeoutError:
                pass

            if self._flush_now:
                self._flush_now = False
                await _speak(self._drain(), mood=response_mood)
                self._thinking_active = True
                continue

            if self._buffered and not self._done:
                # Buffer has text but the parent hasn't signaled finish yet.
                # Don't speak partial responses; keep cycling the thinking
                # persona until finish (or a flush for a tool call) arrives.
                if self._thinking_active:
                    self._thinking_active = False
                try:
                    await workflow.wait_condition(
                        lambda: self._done or self._flush_now or not self._buffered,
                        timeout=timedelta(seconds=60),
                        timeout_summary="Wait for finish or flush while buffer is non-empty",
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            if self._thinking_active and not self._done:
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
                # Yield to the workflow event loop between activity calls so
                # the deadlock detector does not trip and so we promptly
                # notice any pending signals (add_text, finish, flush).
                try:
                    await workflow.wait_condition(
                        lambda: self._done or self._flush_now or bool(self._buffered) or not self._thinking_active,
                        timeout=timedelta(milliseconds=1),
                        timeout_summary="Yield between Reachy thinking cycles",
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            try:
                await workflow.wait_condition(
                    lambda: self._done or self._flush_now or bool(self._buffered) or self._thinking_active,
                    timeout=timedelta(seconds=60),
                    timeout_summary="Wait for Reachy speech text",
                )
            except asyncio.TimeoutError:
                pass

        await _speak(self._drain(), mood=response_mood)

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

        return {"spoken": self._spoke}
