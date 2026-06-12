"""Local Reachy Mini voice bridge for a single ThreadBot thread.

Run this on the machine that can access the Reachy Mini SDK/daemon. The bridge
keeps speech I/O pluggable on purpose: wake-word/STT stacks vary widely, while
ThreadBot already owns the LLM workflow and optional TTS endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shlex
import subprocess
import sys
import time
import uuid as uuid_mod
from uuid import UUID

from temporalio.contrib.workflow_streams import WorkflowStreamClient

from app.config import get_llm_config, get_reachy_config, get_settings, load_settings_from_db
from app.temporal_client import connect_temporal_client
from app.workflows.thread_workflow import RunThreadWorkflow


def _strip_wake_word(text: str, wake_word: str) -> str | None:
    text = (text or "").strip()
    wake = (wake_word or "Reachy").strip().lower()
    if not text:
        return None
    lowered = text.lower()
    if lowered == wake:
        return ""
    pattern = re.compile(
        rf"^\s*(?:hey|okay|ok)?[\s,;:!\.\-]*\s*{re.escape(wake)}\b[\s,;:!\.\-]*",
        re.IGNORECASE,
    )
    match = pattern.match(lowered)
    if not match:
        return None
    return text[match.end():].strip(" ,:;!?.-")


async def _read_transcript(args: argparse.Namespace) -> str | None:
    if args.stdin:
        try:
            return await asyncio.to_thread(input, "reachy> ")
        except EOFError:
            return None

    if not args.stt_command:
        await asyncio.sleep(1.0)
        return None

    command = shlex.split(args.stt_command)

    def run_command() -> str:
        completed = subprocess.run(  # noqa: S603 - user-provided local bridge command
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.stt_timeout,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            if stderr:
                print(f"[reachy] STT command failed: {stderr}", flush=True)
            return ""
        return completed.stdout.strip()

    return await asyncio.to_thread(run_command)


async def _save_user_message(thread_id: str, content: str) -> None:
    from app.database import AsyncSessionLocal
    from app.database.crud import add_message, get_thread

    async with AsyncSessionLocal() as db:
        thread = await get_thread(db, UUID(thread_id))
        if not thread:
            raise RuntimeError(f"Thread {thread_id} not found")
        await add_message(
            db,
            UUID(thread_id),
            "user",
            content,
            metadata={"source": "reachy", "sender_name": "Reachy voice"},
        )
        await db.commit()


async def _resolve_bound_thread_id(args: argparse.Namespace) -> str | None:
    if args.thread_id:
        return args.thread_id
    await load_settings_from_db()
    reachy_config = get_reachy_config()
    return str(reachy_config.get("thread_id") or os.environ.get("REACHY_THREAD_ID") or "").strip() or None


async def _run_thread_turn(thread_id: str, prompt: str, reachy_config: dict, on_first_token=None) -> str:
    await _save_user_message(thread_id, prompt)

    llm_config = get_llm_config().copy()
    llm_config["reachy"] = {**reachy_config, "enabled": True, "thread_id": thread_id, "speech_enabled": True}
    llm_config["stream_batch_chars"] = 24

    # Apply per-thread LLM overrides on top of the global config.
    try:
        from uuid import UUID
        from app.database import AsyncSessionLocal
        from app.database.crud import get_thread_llm_overrides
        from app.config import apply_thread_llm_overrides

        async with AsyncSessionLocal() as setup_db:
            try:
                thread_overrides = await get_thread_llm_overrides(setup_db, UUID(thread_id))
            except Exception:
                thread_overrides = {}
            if thread_overrides:
                llm_config = apply_thread_llm_overrides(llm_config, thread_overrides)
    except Exception as exc:
        print(f"[reachy] failed to apply thread LLM overrides: {exc}", flush=True)

    client = await connect_temporal_client()
    settings = get_settings()
    workflow_id = f"reachy-thread-{thread_id}-{uuid_mod.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        RunThreadWorkflow.run,
        {"thread_id": thread_id, "message": prompt, "llm_config": llm_config},
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
    )

    response = []
    saw_token = False
    stream = WorkflowStreamClient.create(client, workflow_id)
    result_task = asyncio.create_task(handle.result())
    try:
        async for item in stream.subscribe(None, result_type=dict):
            if item.topic == "threadbot-model-events":
                raw = item.data
                if raw.get("type") == "response.output_text.delta" and raw.get("delta"):
                    if not saw_token and on_first_token:
                        saw_token = True
                        await on_first_token()
                    response.append(raw["delta"])
                    print(raw["delta"], end="", flush=True)
            elif item.topic == "events":
                event = item.data
                if event.get("type") in {"tool_call", "tool_result", "thinking"}:
                    label = event.get("tool") or event.get("content") or event.get("type")
                    print(f"\n[reachy] {event.get('type')}: {str(label)[:180]}", flush=True)
            if result_task.done():
                break
    finally:
        await result_task
    print("", flush=True)
    return "".join(response).strip()


async def _speak_response(text: str, reachy_config: dict) -> None:
    if not text:
        return
    from app.activities.llm_activities import _synthesize_speech_audio
    from app.reachy_client import speak_wav

    llm_config = get_llm_config().copy()
    result = await _synthesize_speech_audio(text, llm_config, {"audio_format": "wav"})
    if isinstance(result, str):
        print(f"[reachy] TTS unavailable: {result}", flush=True)
        return
    audio, content_type, _filename = result
    if "wav" not in content_type.lower():
        print(f"[reachy] TTS returned {content_type}; robot playback currently expects WAV.", flush=True)
        return
    await asyncio.to_thread(speak_wav, {**reachy_config, "media_backend": "default"}, audio)


async def run_bridge(args: argparse.Namespace) -> None:
    await load_settings_from_db()
    reachy_config = get_reachy_config()
    wake_word = args.wake_word or reachy_config.get("wake_word") or "Reachy"
    reachy_config = {**reachy_config, "enabled": True, "media_backend": args.media_backend or reachy_config.get("media_backend") or "default"}

    from app.reachy_client import play_animation, play_mood_animation

    initial_thread_id = await _resolve_bound_thread_id(args)
    binding_text = initial_thread_id or "no thread yet; connect one in ThreadBot UI"
    print(f"[reachy] Listening for wake word {wake_word!r}; bound to {binding_text}", flush=True)
    if not args.stdin and not args.stt_command:
        print("[reachy] No input source configured. Use --stdin for testing or --stt-command for voice transcripts.", flush=True)
    awake_until = 0.0
    while True:
        transcript = await _read_transcript(args)
        if transcript is None:
            break
        prompt = _strip_wake_word(transcript, wake_word)
        if prompt is None:
            if time.monotonic() < awake_until:
                prompt = transcript.strip()
            else:
                continue
        if not prompt:
            try:
                await asyncio.to_thread(play_animation, reachy_config, "wake", 1.0)
            except Exception as exc:
                print(f"[reachy] Wake animation failed: {exc}", flush=True)
            awake_until = time.monotonic() + float(args.awake_timeout)
            print(f"[reachy] Awake for {args.awake_timeout:.0f}s. Say the request.", flush=True)
            continue

        thread_id = await _resolve_bound_thread_id(args)
        if not thread_id:
            print("[reachy] No ThreadBot thread is connected to Reachy. Connect one in the ThreadBot UI.", flush=True)
            await asyncio.to_thread(play_animation, reachy_config, "sleep", 1.0)
            continue
        turn_reachy_config = {**reachy_config, "thread_id": thread_id}
        awake_until = 0.0
        print(f"[reachy] Heard: {prompt}", flush=True)
        try:
            await asyncio.to_thread(play_animation, turn_reachy_config, "wake", 1.0)
        except Exception as exc:
            print(f"[reachy] Wake animation failed: {exc}", flush=True)
        async def stop_thinking() -> None:
            return None

        try:
            await asyncio.to_thread(play_mood_animation, turn_reachy_config, "thoughtful")
        except Exception as exc:
            print(f"[reachy] Thinking mood failed: {exc}", flush=True)

        response = await _run_thread_turn(thread_id, prompt, turn_reachy_config, on_first_token=stop_thinking)

        if args.direct_speak:
            await _speak_response(response, turn_reachy_config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind Reachy Mini voice input/output to one ThreadBot thread.")
    parser.add_argument("--thread-id", help="Optional fixed ThreadBot thread UUID. If omitted, uses the thread connected to Reachy in the UI.")
    parser.add_argument("--wake-word", default="", help="Wake word prefix. Defaults to REACHY_WAKE_WORD or Reachy.")
    parser.add_argument("--media-backend", default="default", help="Reachy SDK media backend for bridge audio/camera.")
    parser.add_argument("--stdin", action="store_true", help="Use terminal lines as transcripts for testing.")
    parser.add_argument("--stt-command", default="", help="Command that blocks until one transcript is available and prints it.")
    parser.add_argument("--stt-timeout", type=float, default=120.0, help="Seconds before killing one STT command invocation.")
    parser.add_argument("--awake-timeout", type=float, default=12.0, help="Seconds after a bare wake word to accept the next transcript without repeating the wake word.")
    parser.add_argument("--direct-speak", action="store_true", help="Fallback mode: speak the final response directly from the bridge instead of the Temporal speech workflow.")
    args = parser.parse_args()
    try:
        asyncio.run(run_bridge(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"[reachy] bridge failed: {exc}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
