from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import defn, execute_activity, init, run, signal

from app.activities.reachy_activities import (
    play_reachy_animation,
    play_reachy_mood,
    set_reachy_volume,
    synthesize_and_speak_reachy_text,
)


@defn
class ReachySpeechWorkflow:
    """Reachy speech workflow with thinking, mood, and speaking personas.

    Operates in two phases:

    Phase 1 — "thinking": Loops playing the thinking mood persona
    (``play_reachy_mood`` + ``play_reachy_animation("thinking")``)
    until the parent signals ``finish`` with the final LLM text.
    Once ``finish`` arrives, the workflow calls ``continue_as_new``
    to reset its event history, preventing TMPRL1101 deadlocks
    caused by replaying accumulated events past the SDK's 2-second
    yield window.

    Phase 2 — "speaking": Starts fresh after ``continue_as_new``
    with only the text and config. Plays the response mood persona
    once, then speaks the full text via
    ``synthesize_and_speak_reachy_text``, then plays the sleep
    animation.

    The ``flush`` signal is used during tool-call pauses: the parent
    signals ``flush`` to speak intermediate text (tool results, etc.)
    before the final response. After a flush, the workflow resumes
    the thinking persona until ``finish`` arrives.
    """

    @init
    def __init__(self, input: dict) -> None:
        phase = (input or {}).get("_phase") or "thinking"
        self._phase: str = phase
        self._buffered: list[str] = list((input or {}).get("_buffered") or [])
        self._done = bool((input or {}).get("_done"))
        self._flush_now = bool((input or {}).get("_flush_now"))
        self._thinking_active = bool((input or {}).get("start_thinking", True))
        self._spoke = bool((input or {}).get("_spoke"))
        self._interrupted = bool((input or {}).get("_interrupted"))
        self._thinking_mood_played = False

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

    @run
    async def run(self, input: dict) -> dict:
        llm_config = input.get("llm_config") or {}
        reachy_config = input.get("reachy") or {}
        post_speech_sleep_delay = float(reachy_config.get("post_speech_sleep_delay") or 2.0)
        output_volume = int(reachy_config.get("output_volume") or 100)
        response_mood = str(reachy_config.get("response_mood") or "helpful")

        if self._phase == "speaking":
            return await self._run_speaking_phase(input, llm_config, reachy_config, post_speech_sleep_delay, response_mood)

        return await self._run_thinking_phase(input, llm_config, reachy_config, output_volume, response_mood, post_speech_sleep_delay)

    async def _run_thinking_phase(
        self,
        input: dict,
        llm_config: dict,
        reachy_config: dict,
        output_volume: int,
        response_mood: str,
        post_speech_sleep_delay: float,
    ) -> dict:
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

        while not self._done:
            if self._flush_now:
                self._flush_now = False
                text = self._drain()
                if text.strip():
                    mood = self._infer_mood(text) if not self._spoke else None
                    try:
                        if mood and not self._spoke:
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
                            summary="Speak flushed Reachy text",
                        )
                        if isinstance(result, dict) and result.get("spoken"):
                            self._spoke = True
                    except Exception:
                        workflow.logger.exception("Reachy flushed speech failed")
                    self._thinking_mood_played = False
                self._thinking_active = True
                continue

            if self._thinking_active and not self._done:
                if not self._thinking_mood_played:
                    try:
                        await execute_activity(
                            play_reachy_mood,
                            {"mood": "thoughtful", "reachy": reachy_config},
                            start_to_close_timeout=timedelta(seconds=20),
                            heartbeat_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            summary="Play Reachy thinking mood persona",
                        )
                    except Exception:
                        workflow.logger.exception("Reachy thinking mood failed")
                    self._thinking_mood_played = True

                try:
                    await execute_activity(
                        play_reachy_animation,
                        {"name": "thinking", "duration": 2.0, "reachy": reachy_config},
                        start_to_close_timeout=timedelta(seconds=5),
                        heartbeat_timeout=timedelta(seconds=5),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        summary="Play Reachy thinking animation",
                    )
                except Exception:
                    workflow.logger.exception("Reachy thinking animation failed")
                continue

            if self._buffered and not self._done:
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

            try:
                await workflow.wait_condition(
                    lambda: self._done or self._flush_now or bool(self._buffered) or self._thinking_active,
                    timeout=timedelta(seconds=60),
                    timeout_summary="Wait for Reachy speech text",
                )
            except asyncio.TimeoutError:
                pass

        text = self._drain().strip()
        workflow.continue_as_new(
            args=[
                {
                    "_phase": "speaking",
                    "_text": text,
                    "_spoke": self._spoke,
                    "_interrupted": self._interrupted,
                    "llm_config": llm_config,
                    "reachy": reachy_config,
                    "post_speech_sleep_delay": post_speech_sleep_delay,
                    "response_mood": response_mood,
                }
            ]
        )

    async def _run_speaking_phase(
        self,
        input: dict,
        llm_config: dict,
        reachy_config: dict,
        post_speech_sleep_delay: float,
        response_mood: str,
    ) -> dict:
        text = input.get("_text", "")
        spoke = bool(input.get("_spoke"))
        interrupted = bool(input.get("_interrupted"))

        if text and not interrupted:
            if not spoke:
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
                    synthesize_and_speak_reachy_text,
                    {"texts": [text], "silence_between_seconds": 0.0, "llm_config": llm_config, "reachy": reachy_config},
                    start_to_close_timeout=timedelta(seconds=600),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    summary="Synthesize and speak Reachy response",
                )
                if isinstance(result, dict) and result.get("spoken"):
                    spoke = True
            except Exception:
                workflow.logger.exception("Reachy speech failed")

        if post_speech_sleep_delay > 0 and not interrupted:
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

        return {"spoken": spoke}