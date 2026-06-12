"""Optional Reachy Mini SDK helpers.

This module imports ``reachy_mini`` lazily so the normal ThreadBot backend and
worker still start when the robot SDK is not installed on the host/container.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass
from typing import Any


EMOTION_DATASET = "pollen-robotics/reachy-mini-emotions-library"

MOOD_EMOTIONS: dict[str, str] = {
    "neutral": "helpful1",
    "helpful": "helpful1",
    "cheerful": "cheerful1",
    "excited": "enthusiastic1",
    "grateful": "grateful1",
    "proud": "proud1",
    "thoughtful": "thoughtful1",
    "curious": "curious1",
    "surprised": "surprised1",
    "confused": "confused1",
    "sad": "sad1",
    "calm": "relief1",
    "relieved": "relief1",
    "welcoming": "welcoming1",
    "laughing": "laughing1",
    "tired": "tired1",
    "concerned": "anxiety1",
}


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


def _daemon_base_url(config: dict | None) -> str:
    config = config or {}
    return str(config.get("daemon_url") or "http://localhost:8000").rstrip("/")


def _post_daemon(config: dict | None, endpoint: str, *, body: dict | None = None, timeout: float = 10.0) -> None:
    url = f"{_daemon_base_url(config)}{endpoint}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Reachy daemon returned HTTP {exc.code} for {endpoint}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Reachy daemon is not reachable at {_daemon_base_url(config)}: {exc.reason}") from exc


def play_recorded_move(config: dict | None, dataset: str, move: str) -> str:
    dataset_path = "/".join(urllib.parse.quote(part, safe="") for part in dataset.split("/"))
    move_path = urllib.parse.quote(move, safe="")
    _post_daemon(config, f"/api/move/play/recorded-move-dataset/{dataset_path}/{move_path}")
    return f"Played Reachy recorded move {dataset}/{move}."


def play_mood_animation(config: dict | None, mood: str) -> str:
    mood_key = (mood or "helpful").strip().lower().replace(" ", "_").replace("-", "_")
    emotion = MOOD_EMOTIONS.get(mood_key)
    if emotion is None and mood_key in MOOD_EMOTIONS.values():
        emotion = mood_key
    if emotion is None:
        emotion = MOOD_EMOTIONS["helpful"]
        mood_key = "helpful"
    play_recorded_move(config, EMOTION_DATASET, emotion)
    return f"Played Reachy {mood_key} mood animation ({emotion})."


def goto_pose_via_daemon(config: dict | None, pose: ReachyPose) -> str:
    np, _ReachyMini, create_head_pose = _sdk_imports()
    duration = max(0.2, min(float(pose.duration or 1.0), 10.0))
    head_pose = create_head_pose(
        z=float(pose.z),
        roll=float(pose.roll),
        pitch=float(pose.pitch),
        yaw=float(pose.yaw),
        degrees=True,
        mm=True,
    )
    payload = {
        "head_pose": {"m": np.array(head_pose, dtype=float).flatten().tolist()},
        "antennas": np.deg2rad([float(pose.right_antenna), float(pose.left_antenna)]).tolist(),
        "body_yaw": math.radians(float(pose.body_yaw)),
        "duration": duration,
        "interpolation": "minjerk",
    }
    _post_daemon(config, "/api/move/goto", body=payload, timeout=5.0)
    return (
        "Moved Reachy via daemon: "
        f"head roll={pose.roll:.1f} pitch={pose.pitch:.1f} yaw={pose.yaw:.1f} z={pose.z:.1f}mm, "
        f"body_yaw={pose.body_yaw:.1f}, antennas=({pose.right_antenna:.1f}, {pose.left_antenna:.1f})."
    )


def goto_pose(config: dict | None, pose: ReachyPose) -> str:
    if not (config or {}).get("prefer_sdk_motion"):
        try:
            return goto_pose_via_daemon(config, pose)
        except Exception as exc:
            print(f"[reachy] daemon movement failed, falling back to SDK: {exc}", flush=True)

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
        if abs(float(pose.body_yaw)) > 0.1:
            mini.set_target_body_yaw(np.deg2rad(float(pose.body_yaw)))
            time.sleep(min(duration, 1.0))
    return (
        "Moved Reachy: "
        f"head roll={pose.roll:.1f} pitch={pose.pitch:.1f} yaw={pose.yaw:.1f} z={pose.z:.1f}mm, "
        f"body_yaw={pose.body_yaw:.1f}, antennas=({pose.right_antenna:.1f}, {pose.left_antenna:.1f})."
    )


def play_animation(config: dict | None, name: str, duration: float = 3.0, stop: asyncio.Event | None = None) -> str:
    np, ReachyMini, create_head_pose = _sdk_imports()
    name = (name or "thinking").strip().lower()
    duration = max(0.5, min(float(duration or 3.0), 30.0))
    started = time.monotonic()

    with ReachyMini(**_mini_kwargs(config, media_backend="no_media")) as mini:
        if name == "thinking":
            while time.monotonic() - started < duration and not (stop and stop.is_set()):
                t = time.monotonic() - started
                # Slow, asymmetrical motion reads as pondering instead of twitching.
                pitch = 4.0 + 3.0 * math.sin(t * 0.45)
                roll = 2.8 * math.sin(t * 0.32 + 0.7)
                yaw = 3.5 * math.sin(t * 0.25)
                z = 2.0 * math.sin(t * 0.28 + 1.1)
                right = 18.0 + 5.0 * math.sin(t * 0.4 + 0.2)
                left = 18.0 + 5.0 * math.sin(t * 0.4 + 1.4)
                mini.set_target(
                    head=create_head_pose(z=z, roll=roll, pitch=pitch, yaw=yaw, degrees=True, mm=True),
                    antennas=np.deg2rad([right, left]),
                )
                time.sleep(0.18)
        elif name == "talking":
            while time.monotonic() - started < duration and not (stop and stop.is_set()):
                t = time.monotonic() - started
                # More active than thinking, but low amplitude and continuous.
                pitch = 1.6 * math.sin(t * 1.15) + 0.8 * math.sin(t * 2.2)
                roll = 1.0 * math.sin(t * 0.9 + 0.4)
                yaw = 2.6 * math.sin(t * 0.85)
                z = 1.0 * math.sin(t * 1.0 + 0.8)
                right = 16.0 + 3.5 * math.sin(t * 1.6)
                left = 16.0 + 3.5 * math.sin(t * 1.6 + 1.1)
                mini.set_target(
                    head=create_head_pose(z=z, roll=roll, pitch=pitch, yaw=yaw, degrees=True, mm=True),
                    antennas=np.deg2rad([right, left]),
                )
                time.sleep(0.12)
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


def _capture_image_with_backend(config: dict | None, media_backend: str) -> tuple[Any, str]:
    np, ReachyMini, _create_head_pose = _sdk_imports()
    with ReachyMini(**_mini_kwargs(config, media_backend=media_backend)) as mini:
        frame = mini.media.get_frame()
    if frame is None:
        raise RuntimeError(f"media backend {media_backend!r} returned no camera frame")
    return np.asarray(frame), media_backend


def capture_image_base64(config: dict | None) -> tuple[str, str]:
    config = config or {}
    requested_backend = str(config.get("camera_media_backend") or config.get("media_backend") or "default")
    backends = []
    for backend in (requested_backend, "local", "default", "webrtc"):
        if backend and backend not in backends and backend != "no_media":
            backends.append(backend)

    errors = []
    frame = None
    used_backend = ""
    for backend in backends:
        try:
            frame, used_backend = _capture_image_with_backend(config, backend)
            break
        except Exception as exc:
            errors.append(f"{backend}: {exc}")

    if frame is None:
        raise RuntimeError(
            "Reachy camera capture failed for all media backends. "
            f"Tried {', '.join(backends) or 'none'}. Errors: {' | '.join(errors)}"
        )

    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional local dependency
        raise RuntimeError("Pillow is required to encode Reachy's camera frame. Install `pillow`.") from exc

    image = Image.fromarray(frame.astype("uint8"), "RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    print(f"[reachy-camera] captured frame using media backend {used_backend}", flush=True)
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
    try:
        await asyncio.to_thread(play_animation, config, name, 60.0, stop)
    except Exception as exc:
        print(f"[reachy] animation failed: {exc}", flush=True)
