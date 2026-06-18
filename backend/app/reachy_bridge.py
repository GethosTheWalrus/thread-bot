"""Local Reachy Mini voice bridge for a single ThreadBot thread.

Run this on the machine that can access the Reachy Mini SDK/daemon. The bridge
keeps speech I/O pluggable on purpose: wake-word/STT stacks vary widely, while
ThreadBot already owns the LLM workflow and optional TTS endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid as uuid_mod
from dataclasses import dataclass
from uuid import UUID

from temporalio.contrib.workflow_streams import WorkflowStreamClient

from app.config import get_llm_config, get_reachy_config, get_settings, load_settings_from_db
from app.temporal_client import connect_temporal_client
from app.workflows.thread_workflow import RunThreadWorkflow


def _wake_word_aliases(wake_word: str) -> list[str]:
    wake = (wake_word or "Reachy").strip().lower()
    aliases = [wake]
    if wake == "reachy":
        aliases.extend(["richie", "ritchie", "ricky", "reggie", "regi", "rechie", "reachey"])
    env_aliases = os.environ.get("REACHY_WAKE_ALIASES", "")
    aliases.extend(alias.strip().lower() for alias in env_aliases.split(",") if alias.strip())
    return list(dict.fromkeys(aliases))


def _strip_wake_word(text: str, wake_word: str) -> str | None:
    text = (text or "").strip()
    wake_aliases = _wake_word_aliases(wake_word)
    if not text:
        return None
    lowered = text.lower()
    if lowered in wake_aliases:
        return ""
    pattern = re.compile(
        rf"^\s*(?:hey|okay|ok)?[\s,;:!\.\-]*\s*(?:{'|'.join(re.escape(alias) for alias in wake_aliases)})\b[\s,;:!\.\-]*",
        re.IGNORECASE,
    )
    match = pattern.match(lowered)
    if match:
        return text[match.end():].strip(" ,:;!?.-")

    prefix_pattern = re.compile(r"^\s*(?:hey|okay|ok)?[\s,;:!\.\-]*\s*([a-z][a-z'\-]*)\b[\s,;:!\.\-]*", re.IGNORECASE)
    prefix = prefix_pattern.match(lowered)
    if not prefix:
        return None
    candidate = prefix.group(1).strip("' -")
    if difflib.get_close_matches(candidate, wake_aliases, n=1, cutoff=0.68):
        return text[prefix.end():].strip(" ,:;!?.-")

    # Whisper can prepend a few hallucinated words before the wake word on noisy inputs.
    # Accept a wake-like token near the start, then treat everything after it as the prompt.
    for index, word in enumerate(re.finditer(r"[a-z][a-z'\-]*", lowered, re.IGNORECASE)):
        if index >= 8:
            break
        candidate = word.group(0).strip("' -")
        if difflib.get_close_matches(candidate, wake_aliases, n=1, cutoff=0.68):
            return text[word.end():].strip(" ,:;!?.-")

    # In noisy rooms Whisper may prepend unrelated speech before the actual
    # request. Prefer the last wake-like token so "... Reachy do X" still works.
    last_match = None
    for word in re.finditer(r"[a-z][a-z'\-]*", lowered, re.IGNORECASE):
        candidate = word.group(0).strip("' -")
        if difflib.get_close_matches(candidate, wake_aliases, n=1, cutoff=0.68):
            last_match = word
    if last_match is not None:
        prompt = text[last_match.end():].strip(" ,:;!?.-")
        return prompt or ""
    return None


@dataclass
class VoiceTranscriber:
    source: str
    model_name: str
    device: str
    compute_type: str
    sample_rate: int
    phrase_seconds: float
    silence_threshold: float
    utterance_mode: bool
    utterance_chunk_seconds: float
    utterance_end_silence_seconds: float
    utterance_max_seconds: float
    utterance_start_timeout_seconds: float
    post_wake_end_silence_seconds: float
    post_wake_start_timeout_seconds: float
    language: str | None
    input_device: str | int | None
    reachy_pulse_source: str
    reachy_audio_backend: str
    reachy_use_asoundrc: bool
    reachy_reboot_audio: bool
    reachy_config: dict
    _model: object | None = None
    _wake_model: object | None = None
    _reachy_mini: object | None = None
    _reachy_audio_rebooted: bool = False
    _reachy_recent_live_audio: bool = False
    _reachy_media_released: bool = False
    silent_windows: int = 0
    last_rms: float = 0.0
    last_peak: float = 0.0

    def _log_voice_chunk(self, rms: float, peak: float) -> None:
        if os.environ.get("REACHY_VOICE_LOG_CHUNKS", "false").lower() in {"1", "true", "yes", "on"}:
            print(f"[reachy] Voice chunk: rms={rms:.5f} peak={peak:.5f}", flush=True)

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

    def _load_wake_model(self):
        if self._wake_model is None:
            from pathlib import Path

            import openwakeword
            from openwakeword.utils import download_models

            first_model = next(iter(openwakeword.MODELS.values()), {})
            model_path = first_model.get("model_path") if isinstance(first_model, dict) else None
            if model_path and not Path(model_path).exists():
                download_models()
            print("[reachy] Loading OpenWakeWord detector...", flush=True)
            self._wake_model = openwakeword.Model(inference_framework="onnx")
        return self._wake_model

    def _transcribe_samples(self, samples) -> str:
        import numpy as np

        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        self.last_rms = rms
        self.last_peak = peak
        if peak > 0.001:
            self._reachy_recent_live_audio = True
        print(f"[reachy] Voice level: rms={rms:.5f} peak={peak:.5f}", flush=True)
        if rms < self.silence_threshold:
            self.silent_windows += 1
            return ""
        self.silent_windows = 0

        model = self._load_model()
        transcribe_kwargs = {
            "language": self.language,
            "beam_size": 3,
            "initial_prompt": "Reachy is the wake word for a robot assistant.",
        }
        segments, _info = model.transcribe(samples, vad_filter=True, **transcribe_kwargs)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text and peak >= max(self.silence_threshold * 4.0, 0.04):
            print("[reachy] Whisper VAD returned no text from loud audio; retrying without VAD...", flush=True)
            segments, _info = model.transcribe(samples, vad_filter=False, **transcribe_kwargs)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            print("[reachy] Whisper produced no transcript for this utterance.", flush=True)
        return text

    def _record_pulse_audio(self, source: str, label: str, duration: float | None = None):
        import numpy as np

        with tempfile.NamedTemporaryFile(prefix="reachy_voice_", suffix=".f32", delete=False) as tmp:
            raw_path = tmp.name
        source_args = []
        if source:
            source_args.append(f"device={source}")
        command = [
            "gst-launch-1.0",
            "-q",
            "pulsesrc",
            *source_args,
            "!",
            "audioconvert",
            "!",
            "audioresample",
            "!",
            f"audio/x-raw,rate={self.sample_rate},channels=1,format=F32LE",
            "!",
            "filesink",
            f"location={raw_path}",
        ]
        print(f"[reachy] Listening through {label}...", flush=True)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)  # noqa: S603
        try:
            time.sleep(duration if duration is not None else self.phrase_seconds)
            process.terminate()
            try:
                _stdout, stderr = process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                _stdout, stderr = process.communicate(timeout=2.0)
            if process.returncode not in (0, -15) and stderr:
                raise RuntimeError(stderr.strip())
            audio = np.fromfile(raw_path, dtype=np.float32)
            return audio.astype(np.float32, copy=False), self.sample_rate
        finally:
            try:
                os.remove(raw_path)
            except OSError:
                pass

    def _record_alsa_audio(self, device: str, label: str, duration: float | None = None):
        import numpy as np

        self._setup_reachy_asoundrc()
        self._reboot_reachy_audio_once()
        with tempfile.NamedTemporaryFile(prefix="reachy_voice_", suffix=".f32", delete=False) as tmp:
            raw_path = tmp.name
        command = [
            "gst-launch-1.0",
            "-q",
            "alsasrc",
            f"device={device}",
            "!",
            "audioconvert",
            "!",
            "audioresample",
            "!",
            f"audio/x-raw,rate={self.sample_rate},channels=1,format=F32LE",
            "!",
            "filesink",
            f"location={raw_path}",
        ]
        print(f"[reachy] Listening through {label}...", flush=True)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)  # noqa: S603
        try:
            time.sleep(duration if duration is not None else self.phrase_seconds)
            process.terminate()
            try:
                _stdout, stderr = process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                _stdout, stderr = process.communicate(timeout=2.0)
            if process.returncode not in (0, -15) and stderr:
                raise RuntimeError(stderr.strip())
            audio = np.fromfile(raw_path, dtype=np.float32)
            return audio.astype(np.float32, copy=False), self.sample_rate
        finally:
            try:
                os.remove(raw_path)
            except OSError:
                pass

    def _daemon_url(self) -> str:
        return str(self.reachy_config.get("daemon_url") or "http://127.0.0.1:8000").rstrip("/")

    def _post_reachy_media(self, endpoint: str) -> None:
        request = urllib.request.Request(f"{self._daemon_url()}{endpoint}", method="POST")
        try:
            with urllib.request.urlopen(request, timeout=4.0):
                return
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Reachy daemon media endpoint {endpoint} failed: {exc}") from exc

    def release_reachy_media(self) -> None:
        if self._reachy_media_released:
            return
        self._post_reachy_media("/api/media/release")
        self._reachy_media_released = True

    def acquire_reachy_media(self) -> None:
        if not self._reachy_media_released:
            return
        self._post_reachy_media("/api/media/acquire")
        self._reachy_media_released = False

    def _close_reachy_sdk(self) -> None:
        if self._reachy_mini is None:
            return
        try:
            media = getattr(self._reachy_mini, "media", None)
            if media is not None:
                media.close()
        except Exception:
            pass
        try:
            client = getattr(self._reachy_mini, "client", None)
            if client is not None:
                client.disconnect()
        except Exception:
            pass
        self._reachy_mini = None

    def _setup_reachy_asoundrc(self) -> None:
        if not self.reachy_use_asoundrc:
            return
        try:
            from reachy_mini.media.audio_utils import check_reachymini_asoundrc, write_asoundrc_to_home

            if not check_reachymini_asoundrc():
                write_asoundrc_to_home()
                print("[reachy] Wrote Reachy Mini ALSA aliases to ~/.asoundrc.", flush=True)
        except Exception as exc:
            print(f"[reachy] Reachy Mini ALSA alias setup failed: {exc}", flush=True)

    def _reboot_reachy_audio_once(self) -> None:
        if self._reachy_audio_rebooted or not self.reachy_reboot_audio:
            return
        self._reachy_audio_rebooted = True
        try:
            from reachy_mini.media.audio_control_utils import init_respeaker_usb

            respeaker = init_respeaker_usb()
            if respeaker is None:
                print("[reachy] Reachy Mini audio reboot skipped: XVF3800 USB device not found.", flush=True)
                return
            try:
                print("[reachy] Rebooting Reachy Mini XVF3800 audio chip before capture...", flush=True)
                respeaker.write("REBOOT", [1])
            finally:
                respeaker.close()
            time.sleep(5.0)
            self._setup_reachy_asoundrc()
        except Exception as exc:
            print(f"[reachy] Reachy Mini audio reboot failed: {exc}", flush=True)

    def _get_reachy_sdk(self, *, fresh: bool = False):
        if fresh:
            self._close_reachy_sdk()
        if self._reachy_mini is None:
            self._setup_reachy_asoundrc()
            self._reboot_reachy_audio_once()
            from reachy_mini import ReachyMini

            kwargs = {
                "media_backend": str(self.reachy_config.get("voice_media_backend") or "local"),
                "timeout": 5.0,
            }
            connection_mode = str(self.reachy_config.get("connection_mode") or "").strip()
            if connection_mode:
                kwargs["connection_mode"] = connection_mode
            print(f"[reachy] Opening Reachy SDK audio backend ({kwargs['media_backend']})...", flush=True)
            self._reachy_mini = ReachyMini(**kwargs)
        return self._reachy_mini

    def _record_reachy_sdk_audio(self, duration: float | None = None, *, fresh: bool = False):
        import numpy as np

        duration = duration if duration is not None else self.phrase_seconds
        print("[reachy] Listening through Reachy's SDK microphone...", flush=True)
        reachy = self._get_reachy_sdk(fresh=fresh)
        media = reachy.media
        sample_rate = int(media.get_input_audio_samplerate() or self.sample_rate)
        chunks = []
        media.start_recording()
        deadline = time.monotonic() + max(float(duration), 0.1)
        try:
            while time.monotonic() < deadline:
                sample = media.get_audio_sample()
                if sample is not None:
                    sample = np.asarray(sample, dtype=np.float32)
                    if sample.ndim > 1:
                        sample = sample.mean(axis=1)
                    chunks.append(sample.reshape(-1))
                time.sleep(0.04)
        finally:
            media.stop_recording()
        if not chunks:
            return np.asarray([], dtype=np.float32), sample_rate
        return np.concatenate(chunks).astype(np.float32, copy=False), sample_rate

    def _record_reachy_audio(self, duration: float | None = None):
        backend = (self.reachy_audio_backend or "sdk").strip().lower()
        if backend == "alsa":
            return self._record_alsa_audio("reachymini_audio_src", "Reachy's ALSA microphone", duration)
        if backend == "alsa-release":
            self.release_reachy_media()
            return self._record_alsa_audio("reachymini_audio_src", "Reachy's ALSA microphone", duration)
        if backend == "pulse":
            return self._record_pulse_audio(self.reachy_pulse_source, "Reachy's microphone", duration)
        if backend == "pulse-release":
            self._post_reachy_media("/api/media/release")
            try:
                return self._record_pulse_audio(self.reachy_pulse_source, "Reachy's microphone", duration)
            finally:
                self._post_reachy_media("/api/media/acquire")
        if backend == "sdk-release":
            self.release_reachy_media()
            try:
                return self._record_reachy_sdk_audio(duration, fresh=True)
            finally:
                self._close_reachy_sdk()
        return self._record_reachy_sdk_audio(duration)

    def _record_host_audio(self, duration: float | None = None):
        return self._record_pulse_audio(str(self.input_device or ""), "host microphone", duration)

    def _record_audio(self, duration: float | None = None):
        if self.source == "host":
            return self._record_host_audio(duration)
        return self._record_reachy_audio(duration)

    def _record_and_transcribe(self, *, post_wake: bool = False) -> str:
        if self.utterance_mode:
            samples, sample_rate = self._record_utterance_audio(post_wake=post_wake)
        else:
            samples, sample_rate = self._record_audio()
        if sample_rate != 16000:
            print(f"[reachy] Warning: STT audio sample rate is {sample_rate} Hz; Whisper expects 16 kHz.", flush=True)
        return self._transcribe_samples(samples)

    def _record_utterance_audio(self, *, post_wake: bool = False):
        import numpy as np

        backend = (self.reachy_audio_backend or "sdk").strip().lower()
        if self.source == "reachy" and backend in {"alsa", "alsa-release"}:
            return self._record_alsa_utterance_audio(release_media=backend == "alsa-release", post_wake=post_wake)
        if self.source == "reachy" and backend in {"sdk", "sdk-release"}:
            return self._record_reachy_sdk_utterance_audio(release_media=backend == "sdk-release", post_wake=post_wake)

        chunk_seconds = max(0.25, min(float(self.utterance_chunk_seconds or 0.75), 2.0))
        configured_end_silence = self.post_wake_end_silence_seconds if post_wake else self.utterance_end_silence_seconds
        configured_start_timeout = self.post_wake_start_timeout_seconds if post_wake else self.utterance_start_timeout_seconds
        end_silence_seconds = max(0.25, float(configured_end_silence or 1.2))
        max_seconds = max(chunk_seconds, float(self.utterance_max_seconds or 20.0))
        start_timeout_seconds = max(chunk_seconds, float(configured_start_timeout or self.phrase_seconds))
        started = False
        elapsed = 0.0
        silence_after_speech = 0.0
        chunks = []
        pre_roll = []

        print(
            f"[reachy] Listening for an utterance (max {max_seconds:.0f}s; stop after {end_silence_seconds:.1f}s silence)...",
            flush=True,
        )
        while elapsed < max_seconds:
            samples, sample_rate = self._record_audio(chunk_seconds)
            samples = np.asarray(samples, dtype=np.float32).reshape(-1)
            rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
            peak = float(np.max(np.abs(samples))) if samples.size else 0.0
            self.last_rms = rms
            self.last_peak = peak
            self._log_voice_chunk(rms, peak)
            elapsed += chunk_seconds

            is_speech = rms >= self.silence_threshold
            if not started:
                pre_roll.append(samples)
                pre_roll = pre_roll[-2:]
                if is_speech:
                    started = True
                    chunks.extend(pre_roll)
                    pre_roll = []
                    silence_after_speech = 0.0
                elif elapsed >= start_timeout_seconds:
                    if self.source != "reachy" or self.last_peak <= 0.0001:
                        self.silent_windows += 1
                    return np.asarray([], dtype=np.float32), sample_rate
                continue

            chunks.append(samples)
            if is_speech:
                silence_after_speech = 0.0
            else:
                silence_after_speech += chunk_seconds
                if silence_after_speech >= end_silence_seconds:
                    break

        if not chunks:
            if self.source != "reachy" or self.last_peak <= 0.0001:
                self.silent_windows += 1
            return np.asarray([], dtype=np.float32), self.sample_rate
        self.silent_windows = 0
        return np.concatenate(chunks).astype(np.float32, copy=False), self.sample_rate

    def _record_alsa_utterance_audio(self, *, release_media: bool = False, post_wake: bool = False):
        import numpy as np

        chunk_seconds = max(0.25, min(float(self.utterance_chunk_seconds or 0.75), 2.0))
        configured_end_silence = self.post_wake_end_silence_seconds if post_wake else self.utterance_end_silence_seconds
        configured_start_timeout = self.post_wake_start_timeout_seconds if post_wake else self.utterance_start_timeout_seconds
        end_silence_seconds = max(0.25, float(configured_end_silence or 1.2))
        max_seconds = max(chunk_seconds, float(self.utterance_max_seconds or 20.0))
        start_timeout_seconds = max(chunk_seconds, float(configured_start_timeout or self.phrase_seconds))
        channels = 2
        bytes_per_chunk = max(1, int(self.sample_rate * chunk_seconds) * channels * 2)
        started = False
        elapsed = 0.0
        silence_after_speech = 0.0
        chunks = []
        pre_roll = []
        process = None

        print(
            f"[reachy] Listening for an utterance (max {max_seconds:.0f}s; stop after {end_silence_seconds:.1f}s silence)...",
            flush=True,
        )
        print("[reachy] Listening through Reachy's ALSA microphone...", flush=True)
        self._setup_reachy_asoundrc()
        self._reboot_reachy_audio_once()
        if release_media:
            self.release_reachy_media()
            # The daemon release endpoint can return before the USB audio path is
            # producing valid samples for a new ALSA reader, especially on the Pi.
            # Starting arecord immediately can produce all-zero capture windows.
            time.sleep(float(os.environ.get("REACHY_VOICE_MEDIA_RELEASE_SETTLE_SECONDS", "0.5")))
        try:
            process = subprocess.Popen(
                [
                    "arecord",
                    "-q",
                    "-D",
                    "reachymini_audio_src",
                    "-f",
                    "S16_LE",
                    "-r",
                    str(self.sample_rate),
                    "-c",
                    str(channels),
                    "-t",
                    "raw",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            while elapsed < max_seconds:
                if process.stdout is None:
                    break
                raw = process.stdout.read(bytes_per_chunk)
                if not raw:
                    break
                frame_count = len(raw) // (channels * 2)
                if frame_count <= 0:
                    break
                int_samples = np.frombuffer(raw[: frame_count * channels * 2], dtype=np.int16).reshape(-1, channels)
                samples = (int_samples.astype(np.float32) / 32768.0).mean(axis=1)
                rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
                peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                self.last_rms = rms
                self.last_peak = peak
                self._log_voice_chunk(rms, peak)
                elapsed += chunk_seconds

                is_speech = rms >= self.silence_threshold
                if not started:
                    pre_roll.append(samples)
                    pre_roll = pre_roll[-2:]
                    if is_speech:
                        started = True
                        chunks.extend(pre_roll)
                        pre_roll = []
                        silence_after_speech = 0.0
                    elif elapsed >= start_timeout_seconds:
                        if self.last_peak <= 0.0001:
                            self.silent_windows += 1
                        return np.asarray([], dtype=np.float32), self.sample_rate
                    continue

                chunks.append(samples)
                if is_speech:
                    silence_after_speech = 0.0
                else:
                    silence_after_speech += chunk_seconds
                    if silence_after_speech >= end_silence_seconds:
                        break
        finally:
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                process.send_signal(signal.SIGINT)
                try:
                    _stdout, stderr = process.communicate(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    _stdout, stderr = process.communicate(timeout=2.0)
                stderr_text = stderr.decode(errors="ignore").strip() if stderr else ""
                nonfatal_stderr = "Interrupted system call" in stderr_text or (
                    stderr_text and all("overrun!!!" in line for line in stderr_text.splitlines() if line.strip())
                )
                if process.returncode not in (0, -2, -15) and stderr_text and not nonfatal_stderr:
                    print(f"[reachy] ALSA microphone capture failed: {stderr_text}", flush=True)
            if release_media:
                try:
                    self.acquire_reachy_media()
                except Exception as exc:
                    print(f"[reachy] Reachy media reacquire after ALSA capture failed: {exc}", flush=True)

        if not chunks:
            if self.last_peak <= 0.0001:
                self.silent_windows += 1
            return np.asarray([], dtype=np.float32), self.sample_rate
        self.silent_windows = 0
        return np.concatenate(chunks).astype(np.float32, copy=False), self.sample_rate

    def _record_reachy_sdk_utterance_audio(self, *, release_media: bool = False, post_wake: bool = False):
        import numpy as np

        chunk_seconds = max(0.25, min(float(self.utterance_chunk_seconds or 0.75), 2.0))
        configured_end_silence = self.post_wake_end_silence_seconds if post_wake else self.utterance_end_silence_seconds
        configured_start_timeout = self.post_wake_start_timeout_seconds if post_wake else self.utterance_start_timeout_seconds
        end_silence_seconds = max(0.25, float(configured_end_silence or 1.2))
        max_seconds = max(chunk_seconds, float(self.utterance_max_seconds or 20.0))
        start_timeout_seconds = max(chunk_seconds, float(configured_start_timeout or self.phrase_seconds))
        started = False
        elapsed = 0.0
        silence_after_speech = 0.0
        chunks = []
        pre_roll = []

        print(
            f"[reachy] Listening for an utterance (max {max_seconds:.0f}s; stop after {end_silence_seconds:.1f}s silence)...",
            flush=True,
        )
        print("[reachy] Listening through Reachy's SDK microphone...", flush=True)
        if release_media:
            self.release_reachy_media()
        try:
            reachy = self._get_reachy_sdk(fresh=release_media)
            media = reachy.media
            sample_rate = int(media.get_input_audio_samplerate() or self.sample_rate)
            media.start_recording()
            try:
                while elapsed < max_seconds:
                    deadline = time.monotonic() + chunk_seconds
                    pulled = []
                    while time.monotonic() < deadline:
                        sample = media.get_audio_sample()
                        if sample is not None:
                            sample = np.asarray(sample, dtype=np.float32)
                            if sample.ndim > 1:
                                sample = sample.mean(axis=1)
                            pulled.append(sample.reshape(-1))
                        time.sleep(0.04)
                    samples = np.concatenate(pulled).astype(np.float32, copy=False) if pulled else np.asarray([], dtype=np.float32)
                    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
                    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                    self.last_rms = rms
                    self.last_peak = peak
                    self._log_voice_chunk(rms, peak)
                    elapsed += chunk_seconds

                    is_speech = rms >= self.silence_threshold
                    if not started:
                        pre_roll.append(samples)
                        pre_roll = pre_roll[-2:]
                        if is_speech:
                            started = True
                            chunks.extend(pre_roll)
                            pre_roll = []
                            silence_after_speech = 0.0
                        elif elapsed >= start_timeout_seconds:
                            if self.last_peak <= 0.0001 and not self._reachy_recent_live_audio:
                                self.silent_windows += 1
                            return np.asarray([], dtype=np.float32), sample_rate
                        continue

                    chunks.append(samples)
                    if is_speech:
                        silence_after_speech = 0.0
                    else:
                        silence_after_speech += chunk_seconds
                        if silence_after_speech >= end_silence_seconds:
                            break
            finally:
                media.stop_recording()
        finally:
            if release_media:
                self._close_reachy_sdk()

        if not chunks:
            if self.last_peak <= 0.0001 and not self._reachy_recent_live_audio:
                self.silent_windows += 1
            return np.asarray([], dtype=np.float32), self.sample_rate
        self.silent_windows = 0
        return np.concatenate(chunks).astype(np.float32, copy=False), self.sample_rate

    def _detect_openwakeword(self, wake_model_name: str, threshold: float, duration: float) -> bool:
        import numpy as np

        samples, sample_rate = self._record_audio(duration)
        if sample_rate != 16000:
            print(f"[reachy] Warning: wake-word audio sample rate is {sample_rate} Hz; OpenWakeWord expects 16 kHz.", flush=True)
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        self.last_rms = rms
        self.last_peak = peak
        print(f"[reachy] Wake-word level: rms={rms:.5f} peak={peak:.5f}", flush=True)
        if rms < self.silence_threshold:
            self.silent_windows += 1
            return False
        self.silent_windows = 0

        model = self._load_wake_model()
        model.reset()
        audio = (np.asarray(samples, dtype=np.float32).reshape(-1) * 32767.0).clip(-32768, 32767).astype(np.int16)
        wake_key = wake_model_name.replace(" ", "_").lower()
        best_score = 0.0
        for offset in range(0, max(0, len(audio) - 1279), 1280):
            predictions = model.predict(audio[offset : offset + 1280])
            score = float(predictions.get(wake_key, 0.0))
            best_score = max(best_score, score)
            if score >= threshold:
                print(f"[reachy] OpenWakeWord detected {wake_key!r} ({score:.2f}).", flush=True)
                return True
        if best_score > 0.01:
            print(f"[reachy] OpenWakeWord {wake_key!r} score: {best_score:.2f}", flush=True)
        return False

    async def read_once(self, *, post_wake: bool = False) -> str:
        try:
            return await asyncio.to_thread(self._record_and_transcribe, post_wake=post_wake)
        except Exception as exc:
            print(f"[reachy] voice transcription failed: {exc}", flush=True)
            await asyncio.sleep(1.0)
            return ""

    async def detect_wake_once(self, wake_model_name: str, threshold: float, duration: float) -> bool:
        try:
            return await asyncio.to_thread(self._detect_openwakeword, wake_model_name, threshold, duration)
        except Exception as exc:
            print(f"[reachy] wake-word detection failed: {exc}", flush=True)
            await asyncio.sleep(1.0)
            return False


async def _read_transcript(args: argparse.Namespace, *, post_wake: bool = False) -> str | None:
    if args.stdin:
        try:
            return await asyncio.to_thread(input, "reachy> ")
        except EOFError:
            return None

    if args.voice:
        transcriber = getattr(args, "voice_transcriber", None)
        if transcriber is None:
            raise RuntimeError("Voice mode was enabled but no transcriber was initialized")
        return await transcriber.read_once(post_wake=post_wake)

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


async def _start_thread_turn(thread_id: str, prompt: str, reachy_config: dict) -> tuple[object, str]:
    """Save the user message, start the Temporal workflow, and return
    (workflow_handle, speech_workflow_id). Does NOT wait for the result."""
    await _save_user_message(thread_id, prompt)

    llm_config = get_llm_config().copy()
    llm_config["reachy"] = {
        **reachy_config,
        "enabled": True,
        "thread_id": thread_id,
        "speech_enabled": True,
    }
    llm_config["stream_batch_chars"] = 24

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
                keys = ", ".join(sorted(str(key) for key in thread_overrides.keys()))
                print(f"[reachy] Applying thread LLM overrides for {thread_id}: {keys}", flush=True)
                llm_config = apply_thread_llm_overrides(llm_config, thread_overrides)
            else:
                print(f"[reachy] No thread LLM overrides found for {thread_id}", flush=True)
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
    speech_workflow_id = f"reachy-speech-{workflow_id}"
    return handle, speech_workflow_id


async def _collect_turn_response(handle, *, on_first_token=None) -> str:
    """Stream the workflow response and return the collected text."""
    client = await connect_temporal_client()
    response = []
    saw_token = False
    stream = WorkflowStreamClient.create(client, handle.id)
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
        try:
            await result_task
        except Exception:
            pass
    print("", flush=True)
    return "".join(response).strip()


async def _stream_turn_response(client, workflow_id: str, handle, *, on_first_token=None) -> AsyncIterator[str]:
    """Yield response text deltas from a running workflow stream."""
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
                    yield raw["delta"]
            elif item.topic == "events":
                event = item.data
                if event.get("type") in {"tool_call", "tool_result", "thinking"}:
                    label = event.get("tool") or event.get("content") or event.get("type")
                    print(f"\n[reachy] {event.get('type')}: {str(label)[:180]}", flush=True)
            if result_task.done():
                break
    finally:
        try:
            await result_task
        except Exception:
            pass


async def _interrupt_active_turn(workflow_handle, speech_workflow_id: str | None, reachy_config: dict) -> None:
    """Interrupt an active Reachy turn: signal the speech workflow to stop
    cleanly, then cancel the parent workflow."""
    client = await connect_temporal_client()
    if speech_workflow_id:
        try:
            from app.workflows.reachy_speech_workflow import ReachySpeechWorkflow
            speech_handle = client.get_workflow_handle_for(
                ReachySpeechWorkflow.run,
                workflow_id=speech_workflow_id,
            )
            await speech_handle.signal("interrupt")
            print("[reachy] Sent interrupt signal to speech workflow", flush=True)
        except Exception as exc:
            print(f"[reachy] Failed to signal speech workflow interrupt: {exc}", flush=True)
    if workflow_handle:
        try:
            await workflow_handle.cancel()
            print("[reachy] Cancelled parent workflow", flush=True)
        except Exception as exc:
            print(f"[reachy] Failed to cancel parent workflow: {exc}", flush=True)
    try:
        from app.reachy_client import play_animation
        await asyncio.to_thread(play_animation, reachy_config, "sleep", 1.0)
    except Exception:
        pass


async def _detect_rewake(args: argparse.Namespace, wake_word: str, reachy_config: dict) -> str | None:
    """Listen for a re-wake while a turn is active. Returns the new prompt
    if a wake word is detected, or None if the detection times out or fails.
    During an active turn the Reachy mic may be in use by the speech
    workflow for playback; this uses whatever mic the transcriber currently
    has. Detection failures are non-fatal — the caller will retry."""
    if args.voice:
        transcriber = getattr(args, "voice_transcriber", None)
        if transcriber is not None and args.wake_detector == "openwakeword":
            try:
                detected = await transcriber.detect_wake_once(
                    args.openwakeword_model,
                    float(args.openwakeword_threshold),
                    float(args.openwakeword_window_seconds),
                )
                if detected:
                    transcript = await transcriber.read_once(post_wake=True)
                    prompt = _strip_wake_word(transcript or "", wake_word)
                    return prompt if prompt else transcript.strip() if transcript else ""
            except Exception as exc:
                print(f"[reachy] Re-wake detection error: {exc}", flush=True)
            return None
    # For non-voice modes, just wait and return None (no re-wake possible)
    await asyncio.sleep(5.0)
    return None


async def _speak_response(text: str, reachy_config: dict) -> None:
    if not text:
        return
    from app.activities.llm_activities import _synthesize_speech_audio
    from app.reachy_client import run_animation_background, speak_wav

    llm_config = get_llm_config().copy()
    result = await _synthesize_speech_audio(text, llm_config, {"audio_format": "wav"})
    if isinstance(result, str):
        print(f"[reachy] TTS unavailable: {result}", flush=True)
        return
    audio, content_type, _filename = result
    if "wav" not in content_type.lower():
        print(f"[reachy] TTS returned {content_type}; robot playback currently expects WAV.", flush=True)
        return
    stop_talking = asyncio.Event()
    talking_task = asyncio.create_task(run_animation_background(reachy_config, "talking", stop_talking))
    try:
        await asyncio.to_thread(speak_wav, {**reachy_config, "media_backend": "default"}, audio)
    finally:
        stop_talking.set()
        await talking_task


async def _set_bridge_sleeping(reachy_config: dict, args: argparse.Namespace, sleeping: bool, current_state: bool | None) -> bool | None:
    if not args.robot_sleep_on_idle or current_state is sleeping:
        return current_state
    from app.reachy_client import goto_sleep, wake_up, _daemon_media_available

    action = "sleep" if sleeping else "wake"
    try:
        # Only attempt media acquire if the daemon actually has a media server
        # (i.e. not running with --no-media). Otherwise this just wastes 4s.
        if await asyncio.to_thread(_daemon_media_available, reachy_config):
            def acquire_daemon_media() -> None:
                daemon_url = str(reachy_config.get("daemon_url") or "http://127.0.0.1:8000").rstrip("/")
                request = urllib.request.Request(f"{daemon_url}/api/media/acquire", method="POST")
                with urllib.request.urlopen(request, timeout=4.0):
                    return

            try:
                await asyncio.to_thread(acquire_daemon_media)
            except Exception as exc:
                print(f"[reachy] Failed to acquire daemon media before {action}: {exc}", flush=True)
        if sleeping:
            print(f"[reachy] goto_sleep (media available={await asyncio.to_thread(_daemon_media_available, reachy_config)})", flush=True)
            await asyncio.to_thread(goto_sleep, reachy_config)
        else:
            print(f"[reachy] wake_up (media available={await asyncio.to_thread(_daemon_media_available, reachy_config)})", flush=True)
            await asyncio.to_thread(wake_up, reachy_config)
        return sleeping
    except Exception as exc:
        print(f"[reachy] {action.title()} failed: {exc}", flush=True)
        return current_state


async def run_bridge(args: argparse.Namespace) -> None:
    await load_settings_from_db()
    reachy_config = get_reachy_config()
    wake_word = args.wake_word or reachy_config.get("wake_word") or "Reachy"
    reachy_config = {**reachy_config, "enabled": True, "media_backend": args.media_backend or reachy_config.get("media_backend") or "default"}

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
            utterance_mode=args.voice_utterance_mode,
            utterance_chunk_seconds=args.voice_utterance_chunk_seconds,
            utterance_end_silence_seconds=args.voice_utterance_end_silence_seconds,
            utterance_max_seconds=args.voice_utterance_max_seconds,
            utterance_start_timeout_seconds=args.voice_utterance_start_timeout_seconds,
            post_wake_end_silence_seconds=args.voice_post_wake_end_silence_seconds,
            post_wake_start_timeout_seconds=args.voice_post_wake_start_timeout_seconds,
            language=args.voice_language or None,
            input_device=args.voice_input_device or None,
            reachy_pulse_source=args.voice_pulse_source,
            reachy_audio_backend=args.voice_reachy_backend,
            reachy_use_asoundrc=args.voice_reachy_asoundrc,
            reachy_reboot_audio=args.voice_reachy_reboot_audio,
            reachy_config=reachy_config,
        )
    if not args.stdin and not args.stt_command and not args.voice:
        print("[reachy] No input source configured. Use --stdin, --voice, or --stt-command.", flush=True)
    awake_until = 0.0
    robot_sleeping: bool | None = None
    robot_sleeping = await _set_bridge_sleeping(reachy_config, args, True, robot_sleeping)
    while True:
        if awake_until and time.monotonic() >= awake_until:
            awake_until = 0.0
            robot_sleeping = await _set_bridge_sleeping(reachy_config, args, True, robot_sleeping)

        if args.voice and args.wake_detector == "openwakeword" and time.monotonic() >= awake_until:
            transcriber = getattr(args, "voice_transcriber", None)
            if transcriber is None:
                raise RuntimeError("Voice mode was enabled but no transcriber was initialized")
            detected = await transcriber.detect_wake_once(
                args.openwakeword_model,
                float(args.openwakeword_threshold),
                float(args.openwakeword_window_seconds),
            )
            if not detected:
                if (
                    transcriber.source == "reachy"
                    and int(args.voice_reachy_silence_fallback_windows) > 0
                    and transcriber.silent_windows >= int(args.voice_reachy_silence_fallback_windows)
                ):
                    transcriber.source = "host"
                    transcriber.silent_windows = 0
                    print(
                        "[reachy] Reachy microphone is producing silence; falling back to host microphone. "
                        "Set REACHY_VOICE_SOURCE=reachy to retry Reachy-only or REACHY_VOICE_SOURCE=host to start here.",
                        flush=True,
                    )
                continue
            robot_sleeping = await _set_bridge_sleeping(reachy_config, args, False, robot_sleeping)
            awake_until = time.monotonic() + float(args.awake_timeout)
            print(f"[reachy] Wake word detected. Listening for a request for {args.awake_timeout:.0f}s.", flush=True)
            continue

        transcript = await _read_transcript(args, post_wake=bool(awake_until and time.monotonic() < awake_until))
        if transcript is None:
            break
        if args.voice and not transcript.strip():
            transcriber = getattr(args, "voice_transcriber", None)
            if (
                transcriber is not None
                and transcriber.source == "reachy"
                and int(args.voice_reachy_silence_fallback_windows) > 0
                and transcriber.silent_windows >= int(args.voice_reachy_silence_fallback_windows)
            ):
                transcriber.source = "host"
                transcriber.silent_windows = 0
                print(
                    "[reachy] Reachy microphone is producing silence; falling back to host microphone. "
                    "Set REACHY_VOICE_SOURCE=reachy to retry Reachy-only or REACHY_VOICE_SOURCE=host to start here.",
                    flush=True,
                )
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
            robot_sleeping = await _set_bridge_sleeping(reachy_config, args, False, robot_sleeping)
            awake_until = time.monotonic() + float(args.awake_timeout)
            print(f"[reachy] Wake word detected. Listening for a request for {args.awake_timeout:.0f}s.", flush=True)
            continue

        thread_id = await _resolve_bound_thread_id(args)
        if not thread_id:
            print("[reachy] No ThreadBot thread is connected to Reachy. Connect one in the ThreadBot UI.", flush=True)
            awake_until = 0.0
            robot_sleeping = await _set_bridge_sleeping(reachy_config, args, True, robot_sleeping)
            continue
        turn_reachy_config = {**reachy_config, "thread_id": thread_id, "post_speech_sleep_delay": float(args.post_speech_sleep_delay)}
        awake_until = 0.0
        print(f"[reachy] Heard: {prompt}", flush=True)
        transcriber = getattr(args, "voice_transcriber", None)
        if transcriber is not None:
            try:
                await asyncio.to_thread(transcriber.acquire_reachy_media)
            except Exception as exc:
                print(f"[reachy] Failed to reacquire Reachy media before response: {exc}", flush=True)
        robot_sleeping = await _set_bridge_sleeping(turn_reachy_config, args, False, robot_sleeping)

        # Start the turn workflow and get handles immediately so we can
        # interrupt if the user re-wakes during thinking/speaking.
        try:
            workflow_handle, speech_workflow_id = await _start_thread_turn(thread_id, prompt, turn_reachy_config)
        except Exception as exc:
            print(f"[reachy] Failed to start turn: {exc}", flush=True)
            robot_sleeping = await _set_bridge_sleeping(turn_reachy_config, args, True, robot_sleeping)
            continue

        # Stream the response concurrently with re-wake detection.
        stream_task = asyncio.create_task(
            _collect_turn_response(workflow_handle),
            name="reachy-stream",
        )
        rewake_prompt = None

        while not stream_task.done():
            rewake_task = asyncio.create_task(
                _detect_rewake(args, wake_word, turn_reachy_config),
                name="reachy-rewake",
            )
            done, pending = await asyncio.wait(
                [stream_task, rewake_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                if t is stream_task:
                    rewake_task.cancel()
                    try:
                        await rewake_task
                    except (asyncio.CancelledError, Exception):
                        pass
                elif t is rewake_task:
                    try:
                        new_prompt = rewake_task.result()
                    except Exception:
                        new_prompt = None
                    if new_prompt is not None:
                        rewake_prompt = new_prompt
                        print("[reachy] Re-wake detected during active turn — interrupting", flush=True)
                        await _interrupt_active_turn(workflow_handle, speech_workflow_id, turn_reachy_config)
                        stream_task.cancel()
                        try:
                            await stream_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        robot_sleeping = await _set_bridge_sleeping(turn_reachy_config, args, True, robot_sleeping)
                        break

        if rewake_prompt is not None:
            prompt = rewake_prompt
            continue

        try:
            response = stream_task.result()
        except Exception as exc:
            print(f"[reachy] Turn failed: {exc}", flush=True)
            robot_sleeping = await _set_bridge_sleeping(turn_reachy_config, args, True, robot_sleeping)
            continue

        if args.direct_speak:
            await _speak_response(response, turn_reachy_config)
            await asyncio.sleep(float(args.post_speech_sleep_delay))
            robot_sleeping = await _set_bridge_sleeping(turn_reachy_config, args, True, robot_sleeping)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind Reachy Mini voice input/output to one ThreadBot thread.")
    parser.add_argument("--thread-id", help="Optional fixed ThreadBot thread UUID. If omitted, uses the thread connected to Reachy in the UI.")
    parser.add_argument("--wake-word", default="", help="Wake word prefix. Defaults to REACHY_WAKE_WORD or Reachy.")
    parser.add_argument("--media-backend", default="default", help="Reachy SDK media backend for bridge audio/camera.")
    parser.add_argument("--stdin", action="store_true", help="Use terminal lines as transcripts for testing.")
    parser.add_argument("--voice", action="store_true", help="Use built-in Whisper transcription. Defaults to Reachy's microphone.")
    parser.add_argument("--voice-source", choices=("reachy", "host"), default=os.environ.get("REACHY_VOICE_SOURCE", "reachy"), help="Microphone source for built-in voice mode.")
    parser.add_argument("--voice-reachy-backend", choices=("sdk", "sdk-release", "alsa", "alsa-release", "pulse", "pulse-release"), default=os.environ.get("REACHY_VOICE_REACHY_BACKEND", "sdk"), help="Capture backend when --voice-source=reachy. alsa uses reachymini_audio_src directly; sdk uses ReachyMini.media; *-release asks the daemon to release media before capture.")
    parser.add_argument("--voice-reachy-asoundrc", action=argparse.BooleanOptionalAction, default=os.environ.get("REACHY_VOICE_REACHY_ASOUNDRC", "false").lower() not in {"0", "false", "no", "off"}, help="Generate/use Reachy's official ALSA reachymini_audio_src/sink aliases before SDK audio capture.")
    parser.add_argument("--voice-reachy-reboot-audio", action=argparse.BooleanOptionalAction, default=os.environ.get("REACHY_VOICE_REACHY_REBOOT_AUDIO", "false").lower() not in {"0", "false", "no", "off"}, help="Reboot the Reachy Mini XVF3800 audio chip once before SDK capture. This mirrors the upstream workaround for all-zero mic samples after USB connect.")
    parser.add_argument("--voice-pulse-source", default=os.environ.get("REACHY_VOICE_PULSE_SOURCE", "alsa_input.usb-Pollen_Robotics_Reachy_Mini_Audio_100025004261401296-00.analog-stereo"), help="PulseAudio/PipeWire source name for Reachy's microphone.")
    parser.add_argument("--voice-model", default=os.environ.get("REACHY_VOICE_MODEL", "base.en"), help="faster-whisper model name/path for built-in voice mode.")
    parser.add_argument("--voice-device", default=os.environ.get("REACHY_VOICE_DEVICE", "cpu"), help="Whisper device: cpu, cuda, or auto.")
    parser.add_argument("--voice-compute-type", default=os.environ.get("REACHY_VOICE_COMPUTE_TYPE", "int8"), help="Whisper compute type, e.g. int8, float16, float32.")
    parser.add_argument("--voice-language", default=os.environ.get("REACHY_VOICE_LANGUAGE", "en"), help="Transcription language hint. Empty enables auto-detect.")
    parser.add_argument("--voice-input-device", default=os.environ.get("REACHY_VOICE_INPUT_DEVICE", ""), help="Optional host sounddevice input device name or index when --voice-source=host.")
    parser.add_argument("--voice-sample-rate", type=int, default=int(os.environ.get("REACHY_VOICE_SAMPLE_RATE", "16000")), help="Microphone sample rate for built-in voice mode.")
    parser.add_argument("--voice-phrase-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_PHRASE_SECONDS", "5.0")), help="Seconds to record for each transcription window.")
    parser.add_argument("--voice-silence-threshold", type=float, default=float(os.environ.get("REACHY_VOICE_SILENCE_THRESHOLD", "0.01")), help="RMS threshold below which microphone audio is treated as silence.")
    parser.add_argument("--voice-utterance-mode", action=argparse.BooleanOptionalAction, default=os.environ.get("REACHY_VOICE_UTTERANCE_MODE", "true").lower() not in {"0", "false", "no", "off"}, help="Record until speech ends instead of transcribing fixed windows.")
    parser.add_argument("--voice-utterance-chunk-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_UTTERANCE_CHUNK_SECONDS", "0.75")), help="Audio chunk size used for utterance speech/silence detection.")
    parser.add_argument("--voice-utterance-end-silence-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_UTTERANCE_END_SILENCE_SECONDS", "1.4")), help="Silence duration after speech before an utterance is transcribed.")
    parser.add_argument("--voice-utterance-max-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_UTTERANCE_MAX_SECONDS", "25.0")), help="Maximum utterance recording length before forced transcription.")
    parser.add_argument("--voice-utterance-start-timeout-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_UTTERANCE_START_TIMEOUT_SECONDS", "6.0")), help="Seconds to wait for speech before returning an empty transcript.")
    parser.add_argument("--voice-post-wake-end-silence-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_POST_WAKE_END_SILENCE_SECONDS", "2.4")), help="Silence duration after speech for the request captured immediately after a bare wake word.")
    parser.add_argument("--voice-post-wake-start-timeout-seconds", type=float, default=float(os.environ.get("REACHY_VOICE_POST_WAKE_START_TIMEOUT_SECONDS", "12.0")), help="Seconds to wait for request speech after a bare wake word.")
    parser.add_argument("--voice-reachy-silence-fallback-windows", type=int, default=int(os.environ.get("REACHY_VOICE_REACHY_SILENCE_FALLBACK_WINDOWS", "3")), help="Silent Reachy microphone windows before falling back to host microphone. Defaults to 3 to match the desktop Reachy bridge behavior.")
    parser.add_argument("--wake-detector", choices=("transcript", "openwakeword"), default=os.environ.get("REACHY_WAKE_DETECTOR", "transcript"), help="Wake detection mode. transcript uses Whisper text matching; openwakeword gates Whisper with OpenWakeWord first.")
    parser.add_argument("--openwakeword-model", default=os.environ.get("REACHY_OPENWAKEWORD_MODEL", "alexa"), help="OpenWakeWord model key to use, for example alexa or hey_jarvis.")
    parser.add_argument("--openwakeword-threshold", type=float, default=float(os.environ.get("REACHY_OPENWAKEWORD_THRESHOLD", "0.5")), help="OpenWakeWord activation threshold.")
    parser.add_argument("--openwakeword-window-seconds", type=float, default=float(os.environ.get("REACHY_OPENWAKEWORD_WINDOW_SECONDS", "1.5")), help="Seconds of audio to score per OpenWakeWord detection pass.")
    parser.add_argument("--stt-command", default="", help="Command that blocks until one transcript is available and prints it.")
    parser.add_argument("--stt-timeout", type=float, default=120.0, help="Seconds before killing one STT command invocation.")
    parser.add_argument("--awake-timeout", type=float, default=12.0, help="Seconds after a bare wake word or OpenWakeWord trigger to accept the next transcript without repeating the trigger.")
    parser.add_argument("--post-speech-sleep-delay", type=float, default=float(os.environ.get("REACHY_POST_SPEECH_SLEEP_DELAY", "2.0")), help="Seconds to stay awake after speech finishes before returning to sleep.")
    parser.add_argument("--robot-sleep-on-idle", action=argparse.BooleanOptionalAction, default=os.environ.get("REACHY_ROBOT_SLEEP_ON_IDLE", "true").lower() not in {"0", "false", "no", "off"}, help="Use Reachy's exact daemon sleep pose while waiting and daemon wake routine after detection.")
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
