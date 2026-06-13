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
        self._thinking_active = False
        self._thinking_mood_played = False

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
            return pending.strip(), ""

        split_at = -1
        for idx, char in enumerate(pending):
            if char in ".!?\n" and idx >= 24:
                split_at = idx + 1
        if split_at < 0 and len(pending) < 80:
            return "", pending
        if split_at < 0 and len(pending) >= 220:
            split_at = pending.rfind(" ", 0, 220)
        if split_at <= 0:
            return "", pending
        return pending[:split_at].strip(), pending[split_at:].lstrip()

    def _infer_mood(self, text: str) -> str:
        normalized = text.lower()
        if any(word in normalized for word in ("haha", "lol", "funny", "joke", "laugh")):
            return "laughing"
        if any(word in normalized for word in ("great", "excellent", "awesome", "good news", "success", "done", "perfect")):
            return "cheerful"
        if any(word in normalized for word in ("thank", "appreciate", "grateful")):
            return "grateful"
        if any(word in normalized for word in ("wow", "surpris", "unexpected", "amazing")):
            return "surprised"
        if any(word in normalized for word in ("sorry", "unfortunately", "sad", "bad news", "problem", "failed", "can't")):
            return "sad"
        if any(word in normalized for word in ("not sure", "unclear", "confus", "maybe", "might", "depends")):
            return "confused"
        if any(word in normalized for word in ("let me", "think", "consider", "probably", "investigate", "look into")):
            return "thoughtful"
        if any(word in normalized for word in ("interesting", "curious", "question", "wonder")):
            return "curious"
        if any(word in normalized for word in ("safe", "fine", "okay", "no rain", "clear", "calm")):
            return "relieved"
        return "helpful"

    @run
    async def run(self, input: dict) -> dict:
        with workflow.unsafe.imports_passed_through():
            from app.activities.reachy_activities import play_reachy_mood, speak_reachy_text

        pending = ""
        spoken_chunks = 0
        mood_played = False
        llm_config = input.get("llm_config") or {}
        reachy_config = input.get("reachy") or {}

        while not self._done or self._chunks or pending.strip():
            if not self._chunks and not pending.strip():
                if self._thinking_active:
                    if not self._thinking_mood_played:
                        try:
                            await execute_activity(
                                play_reachy_mood,
                                {"mood": "thoughtful", "reachy": reachy_config},
                                start_to_close_timeout=timedelta(seconds=20),
                                heartbeat_timeout=timedelta(seconds=10),
                                retry_policy=RetryPolicy(maximum_attempts=1),
                                summary="Play Reachy thinking mood",
                            )
                        except Exception:
                            workflow.logger.exception("Reachy thinking mood failed")
                        self._thinking_mood_played = True

                    try:
                        await workflow.wait_condition(
                            lambda: self._done or bool(self._chunks) or not self._thinking_active,
                            timeout=timedelta(seconds=10),
                            timeout_summary="Wait while Reachy is thinking",
                        )
                    except asyncio.TimeoutError:
                        pass
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
                continue

            if not mood_played:
                mood = self._infer_mood(text + " " + pending[:160])
                try:
                    result = await execute_activity(
                        play_reachy_mood,
                        {"mood": mood, "reachy": reachy_config},
                        start_to_close_timeout=timedelta(seconds=20),
                        heartbeat_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        summary="Play Reachy response mood",
                    )
                    if isinstance(result, dict) and not result.get("played"):
                        workflow.logger.warning("Reachy mood animation was not played: %s", result.get("error") or result)
                except Exception:
                    workflow.logger.exception("Reachy mood animation failed")
                mood_played = True

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

        return {"spoken_chunks": spoken_chunks, "mood_played": mood_played}
