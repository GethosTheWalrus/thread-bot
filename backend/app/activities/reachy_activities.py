"""Temporal activities that must run on the local Reachy host.

These activities are registered by ``app.reachy_worker`` on the dedicated
Reachy task queue. They are intentionally small wrappers around the optional
Reachy SDK helper module so the Kubernetes worker never imports hardware/media
dependencies.
"""

from __future__ import annotations

import asyncio
import os

from temporalio.activity import defn, heartbeat


def _reachy_config(args: dict) -> dict:
    config = dict(args.get("reachy") or args.get("llm_config", {}).get("reachy") or {})
    config["enabled"] = True
    # Hardware/media access is local to this worker. Let the local process env
    # override values that may have been captured from the Kubernetes config.
    if os.environ.get("REACHY_CONNECTION_MODE") is not None:
        config["connection_mode"] = os.environ.get("REACHY_CONNECTION_MODE") or ""
    if os.environ.get("REACHY_MEDIA_BACKEND") is not None:
        config["media_backend"] = os.environ.get("REACHY_MEDIA_BACKEND") or "default"
    if os.environ.get("REACHY_CAMERA_MEDIA_BACKEND") is not None:
        config["camera_media_backend"] = os.environ.get("REACHY_CAMERA_MEDIA_BACKEND") or "default"
    if os.environ.get("REACHY_DAEMON_URL") is not None:
        config["daemon_url"] = os.environ.get("REACHY_DAEMON_URL") or "http://localhost:8000"
    return config


@defn
async def execute_reachy_tool_activity(args: dict) -> str:
    """Execute one LLM-requested Reachy hardware tool on the local robot host."""
    tool_name = str(args.get("tool_name") or "")
    tool_args = args.get("arguments") or {}
    if not isinstance(tool_args, dict):
        tool_args = {}
    llm_config = args.get("llm_config") or {}
    reachy_config = _reachy_config(args)

    heartbeat({"step": "reachy_tool", "tool": tool_name})

    if tool_name == "reachy_move":
        from app.reachy_client import ReachyPose, goto_pose

        pose = ReachyPose(
            roll=float(tool_args.get("roll") or 0.0),
            pitch=float(tool_args.get("pitch") or 0.0),
            yaw=float(tool_args.get("yaw") or 0.0),
            z=float(tool_args.get("z") or 0.0),
            body_yaw=float(tool_args.get("body_yaw") or 0.0),
            right_antenna=float(tool_args.get("right_antenna") or 0.0),
            left_antenna=float(tool_args.get("left_antenna") or 0.0),
            duration=float(tool_args.get("duration") or 1.0),
        )
        return await asyncio.to_thread(goto_pose, reachy_config, pose)

    if tool_name == "reachy_animation":
        from app.reachy_client import MOOD_EMOTIONS, play_animation, play_mood_animation

        name = str(tool_args.get("name") or "thinking")
        duration = float(tool_args.get("duration") or 3.0)
        if name.strip().lower().replace(" ", "_").replace("-", "_") in MOOD_EMOTIONS:
            return await asyncio.to_thread(play_mood_animation, reachy_config, name)
        return await asyncio.to_thread(play_animation, reachy_config, name, duration)

    if tool_name == "reachy_capture_image":
        from app.reachy_client import capture_image_base64
        from app.activities.llm_activities import _execute_builtin

        question = str(tool_args.get("question") or "Describe what Reachy sees concisely.").strip()
        try:
            image_base64, content_type = await asyncio.to_thread(capture_image_base64, reachy_config)
        except Exception as exc:
            error = f"Reachy camera capture failed: {exc}"
            print(f"[reachy-camera] {error}", flush=True)
            return error
        return await _execute_builtin(
            "describe_image",
            {
                "image_base64": image_base64,
                "content_type": content_type,
                "question": question,
            },
            args.get("thread_id"),
            None,
            None,
            llm_config,
        )

    return f"Error: unknown Reachy tool {tool_name!r}."


@defn
async def play_reachy_mood(args: dict) -> dict:
    """Play one of the smooth recorded emotion choreographies from the daemon."""
    mood = str(args.get("mood") or "helpful")
    reachy_config = _reachy_config(args)

    from app.reachy_client import play_mood_animation

    print(f"[reachy-mood] playing mood: {mood}", flush=True)
    heartbeat({"step": "reachy_mood", "mood": mood})
    try:
        message = await asyncio.to_thread(play_mood_animation, reachy_config, mood)
    except Exception as exc:
        error = f"Reachy mood animation failed: {exc}"
        print(f"[reachy-mood] {error}", flush=True)
        return {"played": False, "mood": mood, "error": error}
    print(f"[reachy-mood] {message}", flush=True)
    return {"played": True, "mood": mood, "message": message}


@defn
async def speak_reachy_text(args: dict) -> dict:
    """Synthesize a text chunk and play it through Reachy locally."""
    text = str(args.get("text") or "").strip()
    if not text:
        return {"spoken": False, "duration": 0.0}

    llm_config = args.get("llm_config") or {}
    reachy_config = _reachy_config(args)
    reachy_config["media_backend"] = (
        os.environ.get("REACHY_SPEECH_MEDIA_BACKEND")
        or os.environ.get("REACHY_MEDIA_BACKEND")
        or reachy_config.get("media_backend")
        or "default"
    )

    from app.activities.llm_activities import _synthesize_speech_audio
    from app.reachy_client import run_animation_background, speak_wav

    print(f"[reachy-speech] speaking chunk ({len(text)} chars): {text[:80]!r}", flush=True)
    heartbeat({"step": "reachy_speech_tts", "chars": len(text)})
    audio_result = await _synthesize_speech_audio(text, llm_config, {"audio_format": "wav"})
    if isinstance(audio_result, str):
        print(f"[reachy-speech] TTS unavailable: {audio_result}", flush=True)
        return {"spoken": False, "duration": 0.0, "error": audio_result}
    audio, content_type, _filename = audio_result
    if "wav" not in content_type.lower():
        error = f"TTS returned {content_type}; expected WAV."
        print(f"[reachy-speech] {error}", flush=True)
        return {"spoken": False, "duration": 0.0, "error": error}

    stop = asyncio.Event()
    animation_task = asyncio.create_task(run_animation_background(reachy_config, "talking", stop))
    try:
        heartbeat({"step": "reachy_speech_playback", "chars": len(text)})
        try:
            duration = await asyncio.to_thread(speak_wav, reachy_config, audio)
        except Exception as exc:
            error = f"Reachy audio playback failed: {exc}"
            print(f"[reachy-speech] {error}", flush=True)
            return {"spoken": False, "duration": 0.0, "error": error}
        print(f"[reachy-speech] played chunk in {duration:.2f}s", flush=True)
    finally:
        stop.set()
        try:
            await animation_task
        except Exception:
            pass

    return {"spoken": True, "duration": duration}
