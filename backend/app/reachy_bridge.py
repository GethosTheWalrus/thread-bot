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
from dataclasses import dataclass
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


@dataclass
class VoiceTranscriber:
    source: str
    model_name: str
    device: str
    compute_type: str
    sample_rate: int
    phrase_seconds: float
    silence_threshold: float
    language: str | None
    input_device: str | int | None
    reachy_config: dict
    _model: object | None = None

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            print(
                f"[reachy] Loading Whisper STT model {self.model_name!r} "
                f"on {self.device} ({self.compute_type})...",
                flush=True,
            )
            self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    def _transcribe_samples(self, samples) -> str:
        import numpy as np

        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        if rms < self.silence_threshold:
            return ""

        model = self._load_model()
        segments, _info = model.transcribe(
            samples,
            language=self.language,
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _record_reachy_audio(self):
        import numpy as np

        from app.reachy_client import _mini_kwargs
        from reachy_mini import ReachyMini

        chunks = []
        print("[reachy] Listening through Reachy's microphone...", flush=True)
        with ReachyMini(**_mini_kwargs(self.reachy_config, media_backend=str(self.reachy_config.get("media_backend") or "default"))) as mini:
            sample_rate = int(mini.media.get_input_audio_samplerate() or self.sample_rate)
            deadline = time.monotonic() + self.phrase_seconds
            mini.media.start_recording()
            try:
                while time.monotonic() < deadline:
                    sample = mini.media.get_audio_sample()
                    if sample is not None:
                        chunks.append(np.asarray(sample, dtype=np.float32))
                    time.sleep(0.02)
            finally:
                mini.media.stop_recording()

        if not chunks:
            return np.asarray([], dtype=np.float32), sample_rate
        audio = np.concatenate(chunks, axis=0)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        return audio.astype(np.float32, copy=False), sample_rate

    def _record_host_audio(self):
        import numpy as np
        import sounddevice as sd

        frames = max(1, int(self.sample_rate * self.phrase_seconds))
        input_device = self.input_device
        if isinstance(input_device, str) and input_device.isdigit():
            input_device = int(input_device)
        print("[reachy] Listening through host microphone...", flush=True)
        audio = sd.rec(
            frames,
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=input_device,
        )
        sd.wait()
        return np.asarray(audio, dtype=np.float32).reshape(-1), self.sample_rate

    def _record_and_transcribe(self) -> str:
        if self.source == "host":
            samples, sample_rate = self._record_host_audio()
        else:
            samples, sample_rate = self._record_reachy_audio()
        if sample_rate != 16000:
            print(f"[reachy] Warning: STT audio sample rate is {sample_rate} Hz; Whisper expects 16 kHz.", flush=True)
        return self._transcribe_samples(samples)

    async def read_once(self) -> str:
        try:
            return await asyncio.to_thread(self._record_and_transcribe)
        except Exception as exc:
            print(f"[reachy] voice transcription failed: {exc}", flush=True)
            await asyncio.sleep(1.0)
            return ""


async def _read_transcript(args: argparse.Namespace) -> str | None:
    if args.stdin:
        try:
            return await asyncio.to_thread(input, "reachy> ")
        except EOFError:
            return None

    if args.voice:
        transcriber = getattr(args, "voice_transcriber", None)
        if transcriber is None:
            raise RuntimeError("Voice mode was enabled but no transcriber was initialized")
        return await transcriber.read_once()

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
    if args.voice:
        args.voice_transcriber = VoiceTranscriber(
            source=args.voice_source,
            model_name=args.voice_model,
            device=args.voice_device,
            compute_type=args.voice_compute_type,
            sample_rate=args.voice_sample_rate,
            phrase_seconds=args.voice_phrase_seconds,
            silence_threshold=args.voice_silence_threshold,
            language=args.voice_language or None,
            input_device=args.voice_input_device or None,
            reachy_config=reachy_config,
        )
    if not args.stdin and not args.stt_command and not args.voice:
        print("[reachy] No input source configured. Use --stdin, --voice, or --stt-command.", flush=True)
    awake_until = 0.0
    while True:
        transcript = await _read_transcript(args)
        if transcript is None:
            break
        if args.voice and not transcript.strip():
            continue
        if args.voice:
            print(f"[reachy] Transcript: {transcript}", flush=True)
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
    parser.add_argument("--voice", action="store_true", help="Use built-in Whisper transcription. Defaults to Reachy's microphone.")
    parser.add_argument("--voice-source", choices=("reachy", "host"), default=os.environ.get("REACHY_VOICE_SOURCE", "reachy"), help="Microphone source for built-in voice mode.")
    parser.add_argument("--voice-model", default=os.environ.get("REACHY_VOICE_MODEL", "base.en"), help="faster-whisper model name/path for built-in voice mode.")
    parser.add_argument("--voice-device", default=os.environ.get("REACHY_VOICE_DEVICE", "cpu"), help="Whisper device: cpu, cuda, or auto.")
    parser.add_argument("--voice-compute-type", default=os.environ.get("REACHY_VOICE_COMPUTE_TYPE", "int8"), help="Whisper compute type, e.g. int8, float16, float32.")
    parser.add_argument("--voice-language", default=os.environ.get("REACHY_VOICE_LANGUAGE", "en"), help="Transcription language hint. Empty enables auto-detect.")
    parser.add_argument("--voice-input-device", default=os.environ.get("REACHY_VOICE_INPUT_DEVICE", ""), help="Optional host sounddevice input device name or index when --voice-source=host.")
    parser.add_argument("--voice-sample-rate", type=int, default=int(os.environ.get("REACHY_VOICE_SAMPLE_RATE", "16000")), help="Microphone sample rate for built-in voice mode.")
    parser.add_argument("--voice-phrase-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_PHRASE_SECONDS", "4.0")), help="Seconds to record for each transcription window.")
    parser.add_argument("--voice-silence-threshold", type=float, default=float(os.environ.get("REACHY_VOICE_SILENCE_THRESHOLD", "0.01")), help="RMS threshold below which microphone windows are ignored.")
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
