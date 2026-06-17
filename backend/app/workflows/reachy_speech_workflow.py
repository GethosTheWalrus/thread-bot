from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import defn, execute_activity, init, run, signal, start_activity, ActivityCancellationType

from app.activities.reachy_activities import (
    play_reachy_animation,
    play_reachy_mood,
    set_reachy_volume,
    synthesize_and_speak_reachy_text,
)


@defn
class ReachySpeechWorkflow:
    """Single-phase Reachy speech workflow with interrupt support.

    While the parent LLM workflow is processing (thinking/tools), this
    workflow loops the thinking persona (mood + animation) continuously.
    When the parent signals ``finish`` with the final text, it plays the
    response mood, speaks the text, and plays the sleep animation.

    The ``interrupt`` signal terminates immediately: it cancels any
    running activity via ``start_activity`` + ``ActivityHandle.cancel()``,
    skips speech, and plays the sleep animation so the robot returns to
    rest without waiting for the current thinking animation or mood to
    finish.

    The ``flush`` signal speaks intermediate text during tool-call
    pauses, then resumes the thinking persona.
    """

    @init
    def __init__(self, input: dict) -> None:
        self._buffered: list[str] = []
        self._announce_queue: list[str] = []
        self._done = False
        self._flush_now = False
        self._thinking_active = bool((input or {}).get("start_thinking", True))
        self._spoke = False
        self._interrupted = False

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
    async def announce(self, text: str) -> None:
        """Queue a short TTS announcement (e.g. tool call narration)."""
        if text:
            self._announce_queue.append(text)

    @signal
    async def finish(self, final_text: str = "") -> None:
        self._done = True
        self._thinking_active = False
        if final_text:
            self._buffered.append(final_text)

    @signal
    async def interrupt(self) -> None:
        self._done = True
        self._interrupted = True
        self._thinking_active = False

    def _drain(self) -> str:
        if not self._buffered:
            return ""
        joined = "".join(self._buffered)
        self._buffered = []
        return joined

    def _infer_mood(self, text: str) -> str:
        normalized = text.lower()
        if any(w in normalized for w in ("haha", "lol", "funny", "joke", "laugh")):
            return "laughing"
        if any(w in normalized for w in ("great", "excellent", "awesome", "good news", "success", "done", "perfect")):
            return "cheerful"
        if any(w in normalized for w in ("thank", "appreciate", "grateful")):
            return "grateful"
        if any(w in normalized for w in ("wow", "surpris", "unexpected", "amazing")):
            return "surprised"
        if any(w in normalized for w in ("sorry", "unfortunately", "sad", "bad news", "problem", "failed", "can't")):
            return "sad"
        if any(w in normalized for w in ("not sure", "unclear", "confus", "maybe", "might", "depends")):
            return "confused"
        if any(w in normalized for w in ("let me", "think", "consider", "probably", "investigate", "look into")):
            return "thoughtful"
        if any(w in normalized for w in ("interesting", "curious", "question", "wonder")):
            return "curious"
        if any(w in normalized for w in ("safe", "fine", "okay", "no rain", "clear", "calm")):
            return "relieved"
        return "helpful"

    async def _run_activity(self, activity_fn, args: dict, *, summary: str,
                            timeout: timedelta = timedelta(seconds=20),
                            heartbeat: timedelta = timedelta(seconds=10)) -> dict | None:
        """Start an activity and race it against the ``interrupt`` signal.
        If ``interrupt`` fires while the activity is running, the activity
        handle is cancelled (TRY_CANCEL) and this returns None immediately."""
        handle = start_activity(
            activity_fn, args,
            start_to_close_timeout=timeout,
            heartbeat_timeout=heartbeat,
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=ActivityCancellationType.TRY_CANCEL,
            summary=summary,
        )
        try:
            await workflow.wait_condition(
                lambda: handle.done() or self._interrupted,
            )
        except asyncio.TimeoutError:
            pass
        if self._interrupted and not handle.done():
            handle.cancel()
            try:
                await handle
            except (asyncio.CancelledError, Exception):
                pass
            return None
        try:
            return handle.result()
        except Exception:
            workflow.logger.exception("Activity %s failed", summary)
            return None

    @run
    async def run(self, input: dict) -> dict:
        llm_config = input.get("llm_config") or {}
        reachy_config = input.get("reachy") or {}
        post_speech_sleep_delay = float(reachy_config.get("post_speech_sleep_delay") or 2.0)
        output_volume = int(reachy_config.get("output_volume") or 100)
        response_mood = str(reachy_config.get("response_mood") or "helpful")

        await self._run_activity(
            set_reachy_volume,
            {"volume": output_volume, "reachy": reachy_config},
            summary="Set Reachy output volume",
            timeout=timedelta(seconds=10),
            heartbeat=timedelta(seconds=5),
        )
        if self._interrupted:
            return await self._sleep_and_exit(reachy_config)

        # ── Thinking phase ──────────────────────────────────────────
        while not self._done:
            if self._flush_now:
                self._flush_now = False
                text = self._drain()
                if text.strip():
                    mood = self._infer_mood(text) if not self._spoke else None
                    if mood and not self._spoke:
                        await self._run_activity(
                            play_reachy_mood,
                            {"mood": mood, "reachy": reachy_config},
                            summary="Play Reachy response mood persona",
                        )
                        if self._interrupted:
                            return await self._sleep_and_exit(reachy_config)
                    result = await self._run_activity(
                        synthesize_and_speak_reachy_text,
                        {"texts": [text], "silence_between_seconds": 0.0, "llm_config": llm_config, "reachy": reachy_config},
                        summary="Speak flushed Reachy text",
                        timeout=timedelta(seconds=600),
                        heartbeat=timedelta(seconds=30),
                    )
                    if isinstance(result, dict) and result.get("spoken"):
                        self._spoke = True
                    if self._interrupted:
                        return await self._sleep_and_exit(reachy_config)
                self._thinking_active = True
                continue

            if self._announce_queue:
                announcements = list(self._announce_queue)
                self._announce_queue = []
                await self._run_activity(
                    synthesize_and_speak_reachy_text,
                    {"texts": announcements, "silence_between_seconds": 0.3, "llm_config": llm_config, "reachy": reachy_config},
                    summary="Speak tool announcement",
                    timeout=timedelta(seconds=60),
                    heartbeat=timedelta(seconds=10),
                )
                if self._interrupted:
                    return await self._sleep_and_exit(reachy_config)
                continue

            if self._thinking_active and not self._done:
                await self._run_activity(
                    play_reachy_mood,
                    {"mood": "thoughtful", "reachy": reachy_config},
                    summary="Play Reachy thinking mood persona",
                )
                if self._interrupted:
                    return await self._sleep_and_exit(reachy_config)

                await self._run_activity(
                    play_reachy_animation,
                    {"name": "thinking", "duration": 2.0, "reachy": reachy_config},
                    summary="Play Reachy thinking animation",
                    timeout=timedelta(seconds=5),
                    heartbeat=timedelta(seconds=5),
                )
                if self._interrupted:
                    return await self._sleep_and_exit(reachy_config)
                continue

            if self._buffered and not self._done:
                self._thinking_active = False
                try:
                    await workflow.wait_condition(
                        lambda: self._done or self._flush_now or self._interrupted or not self._buffered or bool(self._announce_queue),
                        timeout=timedelta(seconds=60),
                    )
                except asyncio.TimeoutError:
                    pass
                if self._interrupted:
                    return await self._sleep_and_exit(reachy_config)
                continue

            try:
                await workflow.wait_condition(
                    lambda: self._done or self._flush_now or bool(self._buffered) or self._thinking_active or self._interrupted or bool(self._announce_queue),
                    timeout=timedelta(seconds=60),
                )
            except asyncio.TimeoutError:
                pass
            if self._interrupted:
                return await self._sleep_and_exit(reachy_config)

        # ── Speaking phase ──────────────────────────────────────────
        text = self._drain().strip()
        if text and not self._interrupted:
            await self._run_activity(
                play_reachy_mood,
                {"mood": response_mood, "reachy": reachy_config},
                summary="Play Reachy response mood persona",
            )
            if self._interrupted:
                return await self._sleep_and_exit(reachy_config)

            result = await self._run_activity(
                synthesize_and_speak_reachy_text,
                {"texts": [text], "silence_between_seconds": 0.0, "llm_config": llm_config, "reachy": reachy_config},
                summary="Synthesize and speak Reachy response",
                timeout=timedelta(seconds=600),
                heartbeat=timedelta(seconds=30),
            )
            if isinstance(result, dict) and result.get("spoken"):
                self._spoke = True

        if post_speech_sleep_delay > 0 and not self._interrupted:
            await workflow.sleep(timedelta(seconds=post_speech_sleep_delay))

        await self._run_activity(
            play_reachy_animation,
            {"name": "sleep", "duration": 1.0, "reachy": reachy_config},
            summary="Sleep Reachy after speech turn",
        )
        return {"spoken": self._spoke}

    async def _sleep_and_exit(self, reachy_config: dict) -> dict:
        """Play the sleep animation and return immediately (interrupt path)."""
        try:
            await execute_activity(
                play_reachy_animation,
                {"name": "sleep", "duration": 1.0, "reachy": reachy_config},
                start_to_close_timeout=timedelta(seconds=20),
                heartbeat_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
                summary="Sleep Reachy after interrupt",
            )
        except Exception:
            workflow.logger.exception("Reachy sleep after interrupt failed")
        return {"spoken": self._spoke, "interrupted": True}