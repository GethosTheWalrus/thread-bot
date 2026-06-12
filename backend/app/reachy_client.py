"""Optional Reachy Mini SDK helpers.

This module imports ``reachy_mini`` lazily so the normal ThreadBot backend and
worker still start when the robot SDK is not installed on the host/container.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import time
import wave
from dataclasses import dataclass
from typing import Any


@dataclass
class ReachyPose:
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    z: float = 0.0
    body_yaw: float = 0.0
    right_antenna: float = 0.0
    left_antenna: float = 0.0
    duration: float = 1.0


def _sdk_imports():
    try:
        import numpy as np
        from reachy_mini import ReachyMini
        from reachy_mini.utils import create_head_pose
    except Exception as exc:  # pragma: no cover - depends on local robot SDK
        raise RuntimeError(
            "Reachy Mini SDK is not available. Install it on the worker/bridge host with "
            "`pip install reachy-mini`, or run the Reachy voice bridge outside the backend container."
        ) from exc
    return np, ReachyMini, create_head_pose


def _mini_kwargs(config: dict | None, *, media_backend: str | None = None) -> dict[str, Any]:
    config = config or {}
    kwargs: dict[str, Any] = {}
    connection_mode = str(config.get("connection_mode") or "").strip()
    if connection_mode:
        kwargs["connection_mode"] = connection_mode
    backend = media_backend if media_backend is not None else str(config.get("media_backend") or "no_media")
    if backend:
        kwargs["media_backend"] = backend
    return kwargs


def goto_pose(config: dict | None, pose: ReachyPose) -> str:
    np, ReachyMini, create_head_pose = _sdk_imports()
    duration = max(0.2, min(float(pose.duration or 1.0), 10.0))
    with ReachyMini(**_mini_kwargs(config, media_backend="no_media")) as mini:
        mini.goto_target(
            head=create_head_pose(
                z=float(pose.z),
                roll=float(pose.roll),
                pitch=float(pose.pitch),
                yaw=float(pose.yaw),
                degrees=True,
                mm=True,
            ),
            antennas=np.deg2rad([float(pose.right_antenna), float(pose.left_antenna)]),
            body_yaw=np.deg2rad(float(pose.body_yaw)),
            duration=duration,
            method="minjerk",
        )
    return (
        "Moved Reachy: "
        f"head roll={pose.roll:.1f} pitch={pose.pitch:.1f} yaw={pose.yaw:.1f} z={pose.z:.1f}mm, "
        f"body_yaw={pose.body_yaw:.1f}, antennas=({pose.right_antenna:.1f}, {pose.left_antenna:.1f})."
    )


def play_animation(config: dict | None, name: str, duration: float = 3.0) -> str:
    np, ReachyMini, create_head_pose = _sdk_imports()
    name = (name or "thinking").strip().lower()
    duration = max(0.5, min(float(duration or 3.0), 30.0))
    started = time.monotonic()

    with ReachyMini(**_mini_kwargs(config, media_backend="no_media")) as mini:
        if name == "thinking":
            while time.monotonic() - started < duration:
                t = time.monotonic() - started
                # Slow, asymmetrical motion reads as pondering instead of twitching.
                pitch = 5.0 + 4.0 * math.sin(t * 0.85)
                roll = 4.0 * math.sin(t * 0.55 + 0.7)
                yaw = 5.0 * math.sin(t * 0.38)
                z = 3.0 * math.sin(t * 0.45 + 1.1)
                right = 18.0 + 7.0 * math.sin(t * 0.75 + 0.2)
                left = 18.0 + 7.0 * math.sin(t * 0.75 + 1.4)
                mini.set_target(
                    head=create_head_pose(z=z, roll=roll, pitch=pitch, yaw=yaw, degrees=True, mm=True),
                    antennas=np.deg2rad([right, left]),
                )
                time.sleep(0.12)
        elif name == "talking":
            while time.monotonic() - started < duration:
                t = time.monotonic() - started
                # More active than thinking, but low amplitude and continuous.
                pitch = 2.0 * math.sin(t * 2.4) + 1.2 * math.sin(t * 4.1)
                roll = 1.6 * math.sin(t * 1.7 + 0.4)
                yaw = 4.0 * math.sin(t * 1.25)
                z = 1.5 * math.sin(t * 2.0 + 0.8)
                right = 16.0 + 6.0 * math.sin(t * 3.0)
                left = 16.0 + 6.0 * math.sin(t * 3.0 + 1.1)
                mini.set_target(
                    head=create_head_pose(z=z, roll=roll, pitch=pitch, yaw=yaw, degrees=True, mm=True),
                    antennas=np.deg2rad([right, left]),
                )
                time.sleep(0.08)
        elif name == "wake":
            mini.goto_target(
                head=create_head_pose(z=8, pitch=-5, degrees=True, mm=True),
                antennas=np.deg2rad([35.0, 35.0]),
                duration=min(duration, 1.2),
                method="cartoon",
            )
        elif name == "sleep":
            mini.goto_target(
                head=create_head_pose(z=-8, pitch=10, degrees=True, mm=True),
                antennas=np.deg2rad([-10.0, -10.0]),
                duration=min(duration, 1.5),
                method="minjerk",
            )
        else:
            return f"Error: unknown Reachy animation {name!r}. Use thinking, talking, wake, or sleep."

    return f"Played Reachy {name} animation for {duration:.1f}s."


def capture_image_base64(config: dict | None) -> tuple[str, str]:
    np, ReachyMini, _create_head_pose = _sdk_imports()
    with ReachyMini(**_mini_kwargs(config, media_backend=str((config or {}).get("media_backend") or "default"))) as mini:
        frame = mini.media.get_frame()

    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional local dependency
        raise RuntimeError("Pillow is required to encode Reachy's camera frame. Install `pillow`.") from exc

    image = Image.fromarray(np.asarray(frame).astype("uint8"), "RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def speak_wav(config: dict | None, audio: bytes) -> float:
    np, ReachyMini, _create_head_pose = _sdk_imports()
    with wave.open(io.BytesIO(audio), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise RuntimeError("Reachy speaker playback currently expects 16-bit PCM WAV audio.")

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    samples = samples.reshape((-1, channels))

    with ReachyMini(**_mini_kwargs(config, media_backend=str((config or {}).get("media_backend") or "default"))) as mini:
        mini.media.start_playing()
        try:
            output_rate = int(mini.media.get_output_audio_samplerate())
            if output_rate != sample_rate:
                from scipy.signal import resample

                target_len = int(len(samples) * output_rate / sample_rate)
                samples = resample(samples, target_len).astype(np.float32)
                sample_rate = output_rate
            mini.media.push_audio_sample(samples)
            duration = len(samples) / float(sample_rate)
            time.sleep(duration)
            return duration
        finally:
            mini.media.stop_playing()


async def run_animation_background(config: dict | None, name: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(play_animation, config, name, 4.0)
        except Exception as exc:
            print(f"[reachy] animation failed: {exc}", flush=True)
            await asyncio.sleep(1.0)
