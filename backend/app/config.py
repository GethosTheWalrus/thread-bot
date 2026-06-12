from pydantic_settings import BaseSettings
import json


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chatbot"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Temporal
    TEMPORAL_HOST: str = "localhost"
    TEMPORAL_PORT: int = 7233
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "chatbot-task-queue"
    TEMPORAL_PAYLOAD_CODEC_ENABLED: bool = False
    TEMPORAL_PAYLOAD_CODEC_KEY: str = ""
    TEMPORAL_PAYLOAD_CODEC_KEY_FILE: str = ""

    # LLM API
    LLM_API_URL: str = "http://host.docker.internal:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MODEL: str = "llama3.1"
    LLM_IMAGE_ENABLED: bool = False
    LLM_IMAGE_API_URL: str = ""
    LLM_IMAGE_MODEL: str = ""
    LLM_IMAGE_PROVIDER: str = "auto"  # auto, ollama, openai_compatible, comfyui
    LLM_VISION_ENABLED: bool = False
    LLM_VISION_API_URL: str = ""
    LLM_VISION_API_KEY: str = ""
    LLM_VISION_MODEL: str = ""
    LLM_VISION_PROVIDER: str = "auto"
    LLM_VISION_MAX_TOKENS: int = 1200
    LLM_VISION_RECIPE_ENABLED: bool = True
    LLM_VISION_PIPELINE_ENABLED: bool = False
    LLM_VISION_OCR_API_URL: str = ""
    LLM_VISION_OCR_MODEL: str = ""
    LLM_VISION_DETAIL_API_URL: str = ""
    LLM_VISION_DETAIL_MODEL: str = ""
    LLM_VISION_STYLE_API_URL: str = ""
    LLM_VISION_STYLE_MODEL: str = ""
    LLM_PROVIDER: str = "auto"  # auto, ollama, llama_cpp, openai
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048
    LLM_STREAM_TIMEOUT: int = 600
    LLM_VIDEO_TOOL_TIMEOUT: int = 2400
    LLM_MAX_ITERATIONS: int = 25
    LLM_CONTEXT_WINDOW: int = 8192
    LLM_COMPACTION_THRESHOLD: float = 0.75
    LLM_PRESERVE_RECENT: int = 10
    LLM_TOOL_RESULT_MAX_CHARS: int = 0  # 0 = no truncation

    # ComfyUI image generation
    LLM_COMFYUI_API_URL: str = "http://ollama.home:8188"
    LLM_COMFYUI_WORKFLOW: str = ""  # workflow JSON; "" means use bundled default
    LLM_COMFYUI_WORKFLOW_PRESETS: str = ""
    LLM_COMFYUI_SELECTED_WORKFLOW: str = "Flux.2 Klein 9B"
    LLM_COMFYUI_OUTPUT_NODE: str = "12"  # node id whose output contains the saved image
    LLM_COMFYUI_NEGATIVE_PROMPT: str = ""
    LLM_COMFYUI_WIDTH: int = 1024
    LLM_COMFYUI_HEIGHT: int = 1024
    LLM_COMFYUI_STEPS: int = 28
    LLM_COMFYUI_CFG: float = 1.0
    LLM_COMFYUI_SAMPLER: str = "euler"
    LLM_COMFYUI_SCHEDULER: str = "simple"
    LLM_COMFYUI_SEED: int = 42

    # ComfyUI video generation (Wan2.2 or compatible workflows)
    LLM_VIDEO_ENABLED: bool = True
    LLM_COMFYUI_VIDEO_WORKFLOW: str = ""
    LLM_COMFYUI_IMAGE_TO_VIDEO_WORKFLOW: str = ""
    LLM_COMFYUI_VIDEO_OUTPUT_NODE: str = ""
    LLM_COMFYUI_VIDEO_INPUT_IMAGE_NODE: str = ""
    LLM_COMFYUI_VIDEO_PROMPT_NODE: str = ""
    LLM_COMFYUI_VIDEO_NEGATIVE_NODE: str = ""
    LLM_COMFYUI_VIDEO_NEGATIVE_PROMPT: str = "low quality, blurry, distorted, watermark, text artifacts"
    # Caps — the agent may request smaller values; the backend clamps
    # duration-derived overrides to these limits. Defaults allow up to
    # 20 seconds at 16 fps with up to 1280x720.
    LLM_COMFYUI_VIDEO_WIDTH: int = 1280
    LLM_COMFYUI_VIDEO_HEIGHT: int = 720
    LLM_COMFYUI_VIDEO_FRAMES: int = 320
    LLM_COMFYUI_VIDEO_FPS: int = 16
    LLM_COMFYUI_VIDEO_STEPS: int = 24
    LLM_COMFYUI_VIDEO_CFG: float = 4.0
    LLM_COMFYUI_VIDEO_SAMPLER: str = "euler"
    LLM_COMFYUI_VIDEO_SCHEDULER: str = "simple"
    LLM_COMFYUI_VIDEO_SEED: int = 42
    LLM_COMFYUI_VIDEO_TIMEOUT: int = 1800

    # Local audio generation for muxed video output
    LLM_AUDIO_ENABLED: bool = True
    LLM_TTS_PROVIDER: str = "openai_compatible"  # openai_compatible, piper_http
    LLM_TTS_API_URL: str = "http://ollama.home:5002/v1/audio/speech"
    LLM_TTS_API_KEY: str = ""
    LLM_TTS_MODEL: str = "piper"
    LLM_TTS_VOICE: str = "en_US-lessac-medium"
    LLM_TTS_FORMAT: str = "wav"
    LLM_TTS_TIMEOUT: int = 300

    # ComfyUI lip-sync stage for dialog-driven video
    LLM_LIPSYNC_ENABLED: bool = True
    LLM_COMFYUI_LIPSYNC_WORKFLOW: str = ""
    LLM_COMFYUI_LIPSYNC_OUTPUT_NODE: str = "47"
    LLM_COMFYUI_LIPSYNC_INPUT_IMAGE_NODE: str = "12"
    LLM_COMFYUI_LIPSYNC_INPUT_AUDIO_NODE: str = "8"
    LLM_COMFYUI_LIPSYNC_PROMPT_NODE: str = "6"
    LLM_COMFYUI_LIPSYNC_NEGATIVE_NODE: str = "7"
    LLM_COMFYUI_LIPSYNC_MODEL: str = "wan2.2_s2v_14B_fp8_scaled.safetensors"
    LLM_COMFYUI_LIPSYNC_PATCH: str = "InfiniteTalk/Wan2_1-InfiniteTalk-Single_fp8_e4m3fn_scaled_KJ.safetensors"
    LLM_COMFYUI_LIPSYNC_AUDIO_ENCODER: str = "wav2vec2_large_english_fp16.safetensors"
    LLM_COMFYUI_LIPSYNC_VAE: str = "wan_2.1_vae.safetensors"
    LLM_COMFYUI_LIPSYNC_CLIP: str = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    LLM_COMFYUI_LIPSYNC_WIDTH: int = 1280
    LLM_COMFYUI_LIPSYNC_HEIGHT: int = 720
    LLM_COMFYUI_LIPSYNC_FRAMES: int = 320
    LLM_COMFYUI_LIPSYNC_FPS: int = 16
    LLM_COMFYUI_LIPSYNC_STEPS: int = 20
    LLM_COMFYUI_LIPSYNC_CFG: float = 6.0
    LLM_COMFYUI_LIPSYNC_AUDIO_SCALE: float = 1.0
    LLM_COMFYUI_LIPSYNC_SEED: int = 42
    LLM_COMFYUI_LIPSYNC_TIMEOUT: int = 2400

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "*"

    # App
    APP_NAME: str = "ThreadBot"
    APP_PUBLIC_BASE_URL: str = ""
    GENERATED_IMAGE_DIR: str = "/tmp/threadbot-generated-images"
    GENERATED_MEDIA_DIR: str = "/tmp/threadbot-generated-media"

    # Discord integration (optional)
    DISCORD_ENABLED: bool = False
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_GUILD_ID: str = ""
    DISCORD_CHANNEL_ID: str = ""
    DISCORD_POLL_INTERVAL_SECONDS: int = 10

    # Reachy Mini integration (optional, local robot/daemon)
    REACHY_ENABLED: bool = False
    REACHY_THREAD_ID: str = ""
    REACHY_WAKE_WORD: str = "Reachy"
    REACHY_CONNECTION_MODE: str = ""  # auto when empty; localhost_only or network when set
    REACHY_MEDIA_BACKEND: str = "no_media"  # no_media for motion tools; default/local/webrtc for camera/audio bridge
    REACHY_TASK_QUEUE: str = "reachy-local"
    REACHY_SPEECH_ENABLED: bool = True

    model_config = {"extra": "ignore"}


# Store overrides separately since Pydantic v2 models are frozen
_settings: Settings | None = None
_overrides: dict = {}


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_setting(key: str):
    """Get a setting value, checking overrides first."""
    key_lower = key.lower()
    if key_lower in _overrides:
        return _overrides[key_lower]
    settings = get_settings()
    upper = key.upper()
    if hasattr(settings, upper):
        return getattr(settings, upper)
    if hasattr(settings, key_lower):
        return getattr(settings, key_lower)
    return None


def update_settings(**kwargs) -> None:
    """Update settings at runtime via an override dict (Pydantic v2 models are frozen)."""
    for key, value in kwargs.items():
        _overrides[key.lower()] = value


async def load_settings_from_db() -> None:
    """Load persisted settings from DB into the override dict.

    Called once during app startup so that DB-stored values take precedence
    over environment variables / Pydantic defaults.
    """
    from app.database import AsyncSessionLocal
    from app.database.crud import get_all_settings

    async with AsyncSessionLocal() as db:
        rows = await get_all_settings(db)

    # Map DB keys (stored lowercase) into the override dict.
    # Coerce numeric types back from their string representation.
    _type_map = {
        "llm_temperature": float,
        "llm_max_tokens": int,
        "llm_stream_timeout": int,
        "llm_video_tool_timeout": int,
        "llm_max_iterations": int,
        "llm_context_window": int,
        "llm_compaction_threshold": float,
        "llm_preserve_recent": int,
        "llm_tool_result_max_chars": int,
        "llm_image_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "llm_vision_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "llm_vision_recipe_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "llm_vision_pipeline_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "llm_vision_max_tokens": int,
        "llm_comfyui_workflow_presets": json.loads,
        "llm_video_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "llm_comfyui_video_width": int,
        "llm_comfyui_video_height": int,
        "llm_comfyui_video_frames": int,
        "llm_comfyui_video_fps": int,
        "llm_comfyui_video_steps": int,
        "llm_comfyui_video_cfg": float,
        "llm_comfyui_video_seed": int,
        "llm_comfyui_video_timeout": int,
        "llm_audio_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "llm_tts_timeout": int,
        "llm_lipsync_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "llm_comfyui_lipsync_width": int,
        "llm_comfyui_lipsync_height": int,
        "llm_comfyui_lipsync_frames": int,
        "llm_comfyui_lipsync_fps": int,
        "llm_comfyui_lipsync_steps": int,
        "llm_comfyui_lipsync_cfg": float,
        "llm_comfyui_lipsync_audio_scale": float,
        "llm_comfyui_lipsync_seed": int,
        "llm_comfyui_lipsync_timeout": int,
        "discord_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "discord_poll_interval_seconds": int,
        "reachy_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "reachy_speech_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
    }
    for key, value in rows.items():
        coerce = _type_map.get(key)
        if coerce:
            try:
                value = coerce(value)
            except (ValueError, TypeError):
                pass
        _overrides[key] = value


def _load_default_comfyui_workflow() -> str:
    """Return the bundled default ComfyUI workflow JSON as a string."""
    import os
    here = os.path.dirname(__file__)
    path = os.path.join(here, "assets", "flux2_klein_9b_workflow.json")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_comfyui_workflow_presets() -> list[dict]:
    """Return saved ComfyUI workflow presets, including the bundled default."""
    presets = [
        {
            "name": "Flux.2 Klein 9B",
            "description": "Default local Flux.2 Klein workflow using qwen_3_8b_fp8mixed and the small decoder VAE.",
            "output_node": "12",
            "workflow": _load_default_comfyui_workflow(),
            "builtin": True,
        }
    ]
    override = get_setting("LLM_COMFYUI_WORKFLOW_PRESETS")
    if not override:
        return presets
    try:
        saved = override if isinstance(override, list) else json.loads(str(override))
    except Exception:
        return presets
    if not isinstance(saved, list):
        return presets
    by_name = {preset["name"]: preset for preset in presets}
    for item in saved:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        workflow = str(item.get("workflow") or "").strip()
        if not name or not workflow:
            continue
        by_name[name] = {
            "name": name,
            "description": str(item.get("description") or ""),
            "output_node": str(item.get("output_node") or ""),
            "workflow": workflow,
            "builtin": bool(item.get("builtin", False)),
        }
    return list(by_name.values())


def get_comfyui_workflow_json() -> str:
    """Return the ComfyUI workflow JSON the user has selected, or the bundled default."""
    selected = str(get_setting("LLM_COMFYUI_SELECTED_WORKFLOW") or "").strip()
    if selected:
        for preset in get_comfyui_workflow_presets():
            if preset.get("name") == selected and str(preset.get("workflow") or "").strip():
                return str(preset["workflow"])
    override = get_setting("LLM_COMFYUI_WORKFLOW")
    if override and str(override).strip():
        return str(override)
    return _load_default_comfyui_workflow()


def get_llm_config() -> dict:
    """Get current LLM config with overrides applied."""
    vision_enabled = bool(get_setting("LLM_VISION_ENABLED"))
    return {
        "api_url": get_setting("LLM_API_URL"),
        "api_key": get_setting("LLM_API_KEY"),
        "model": get_setting("LLM_MODEL"),
        "image_enabled": bool(get_setting("LLM_IMAGE_ENABLED")),
        "image_model": get_setting("LLM_IMAGE_MODEL") or get_setting("LLM_MODEL"),
        "image_api_url": get_setting("LLM_IMAGE_API_URL") or get_setting("LLM_API_URL"),
        "image_provider": get_setting("LLM_IMAGE_PROVIDER") or "auto",
        "public_base_url": get_setting("APP_PUBLIC_BASE_URL") or "",
        "generated_image_dir": get_setting("GENERATED_IMAGE_DIR") or "/tmp/threadbot-generated-images",
        "generated_media_dir": get_setting("GENERATED_MEDIA_DIR") or "/tmp/threadbot-generated-media",
        "comfyui_api_url": (get_setting("LLM_COMFYUI_API_URL") or "").rstrip("/"),
        "comfyui_output_node": str(get_setting("LLM_COMFYUI_OUTPUT_NODE") or "12"),
        "comfyui_negative_prompt": get_setting("LLM_COMFYUI_NEGATIVE_PROMPT") or "",
        "comfyui_width": int(get_setting("LLM_COMFYUI_WIDTH") or 1024),
        "comfyui_height": int(get_setting("LLM_COMFYUI_HEIGHT") or 1024),
        "comfyui_steps": int(get_setting("LLM_COMFYUI_STEPS") or 28),
        "comfyui_cfg": float(get_setting("LLM_COMFYUI_CFG") or 1.0),
        "comfyui_sampler": get_setting("LLM_COMFYUI_SAMPLER") or "euler",
        "comfyui_scheduler": get_setting("LLM_COMFYUI_SCHEDULER") or "simple",
        "comfyui_seed": int(get_setting("LLM_COMFYUI_SEED") or 42),
        "video_enabled": bool(get_setting("LLM_VIDEO_ENABLED")),
        "comfyui_video_workflow": get_setting("LLM_COMFYUI_VIDEO_WORKFLOW") or "",
        "comfyui_image_to_video_workflow": get_setting("LLM_COMFYUI_IMAGE_TO_VIDEO_WORKFLOW") or "",
        "comfyui_video_output_node": str(get_setting("LLM_COMFYUI_VIDEO_OUTPUT_NODE") or ""),
        "comfyui_video_input_image_node": str(get_setting("LLM_COMFYUI_VIDEO_INPUT_IMAGE_NODE") or ""),
        "comfyui_video_prompt_node": str(get_setting("LLM_COMFYUI_VIDEO_PROMPT_NODE") or ""),
        "comfyui_video_negative_node": str(get_setting("LLM_COMFYUI_VIDEO_NEGATIVE_NODE") or ""),
        "comfyui_video_negative_prompt": get_setting("LLM_COMFYUI_VIDEO_NEGATIVE_PROMPT") or "",
        "comfyui_video_width": int(get_setting("LLM_COMFYUI_VIDEO_WIDTH") or 832),
        "comfyui_video_height": int(get_setting("LLM_COMFYUI_VIDEO_HEIGHT") or 480),
        "comfyui_video_frames": int(get_setting("LLM_COMFYUI_VIDEO_FRAMES") or 81),
        "comfyui_video_fps": int(get_setting("LLM_COMFYUI_VIDEO_FPS") or 16),
        "comfyui_video_steps": int(get_setting("LLM_COMFYUI_VIDEO_STEPS") or 24),
        "comfyui_video_cfg": float(get_setting("LLM_COMFYUI_VIDEO_CFG") or 4.0),
        "comfyui_video_sampler": get_setting("LLM_COMFYUI_VIDEO_SAMPLER") or "euler",
        "comfyui_video_scheduler": get_setting("LLM_COMFYUI_VIDEO_SCHEDULER") or "simple",
        "comfyui_video_seed": int(get_setting("LLM_COMFYUI_VIDEO_SEED") or 42),
        "comfyui_video_timeout": int(get_setting("LLM_COMFYUI_VIDEO_TIMEOUT") or 1800),
        "audio_enabled": bool(get_setting("LLM_AUDIO_ENABLED")),
        "tts_provider": get_setting("LLM_TTS_PROVIDER") or "openai_compatible",
        "tts_api_url": (get_setting("LLM_TTS_API_URL") or "").rstrip("/"),
        "tts_api_key": get_setting("LLM_TTS_API_KEY") or "",
        "tts_model": get_setting("LLM_TTS_MODEL") or "piper",
        "tts_voice": get_setting("LLM_TTS_VOICE") or "en_US-lessac-medium",
        "tts_format": get_setting("LLM_TTS_FORMAT") or "wav",
        "tts_timeout": int(get_setting("LLM_TTS_TIMEOUT") or 300),
        "lipsync_enabled": bool(get_setting("LLM_LIPSYNC_ENABLED")),
        "comfyui_lipsync_workflow": get_setting("LLM_COMFYUI_LIPSYNC_WORKFLOW") or "",
        "comfyui_lipsync_output_node": str(get_setting("LLM_COMFYUI_LIPSYNC_OUTPUT_NODE") or "47"),
        "comfyui_lipsync_input_image_node": str(get_setting("LLM_COMFYUI_LIPSYNC_INPUT_IMAGE_NODE") or "12"),
        "comfyui_lipsync_input_audio_node": str(get_setting("LLM_COMFYUI_LIPSYNC_INPUT_AUDIO_NODE") or "8"),
        "comfyui_lipsync_prompt_node": str(get_setting("LLM_COMFYUI_LIPSYNC_PROMPT_NODE") or "6"),
        "comfyui_lipsync_negative_node": str(get_setting("LLM_COMFYUI_LIPSYNC_NEGATIVE_NODE") or "7"),
        "comfyui_lipsync_model": get_setting("LLM_COMFYUI_LIPSYNC_MODEL") or "wan2.2_s2v_14B_fp8_scaled.safetensors",
        "comfyui_lipsync_patch": get_setting("LLM_COMFYUI_LIPSYNC_PATCH") or "InfiniteTalk/Wan2_1-InfiniteTalk-Single_fp8_e4m3fn_scaled_KJ.safetensors",
        "comfyui_lipsync_audio_encoder": get_setting("LLM_COMFYUI_LIPSYNC_AUDIO_ENCODER") or "wav2vec2_large_english_fp16.safetensors",
        "comfyui_lipsync_vae": get_setting("LLM_COMFYUI_LIPSYNC_VAE") or "wan_2.1_vae.safetensors",
        "comfyui_lipsync_clip": get_setting("LLM_COMFYUI_LIPSYNC_CLIP") or "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "comfyui_lipsync_width": int(get_setting("LLM_COMFYUI_LIPSYNC_WIDTH") or 832),
        "comfyui_lipsync_height": int(get_setting("LLM_COMFYUI_LIPSYNC_HEIGHT") or 480),
        "comfyui_lipsync_frames": int(get_setting("LLM_COMFYUI_LIPSYNC_FRAMES") or 81),
        "comfyui_lipsync_fps": int(get_setting("LLM_COMFYUI_LIPSYNC_FPS") or 16),
        "comfyui_lipsync_steps": int(get_setting("LLM_COMFYUI_LIPSYNC_STEPS") or 20),
        "comfyui_lipsync_cfg": float(get_setting("LLM_COMFYUI_LIPSYNC_CFG") or 6.0),
        "comfyui_lipsync_audio_scale": float(get_setting("LLM_COMFYUI_LIPSYNC_AUDIO_SCALE") or 1.0),
        "comfyui_lipsync_seed": int(get_setting("LLM_COMFYUI_LIPSYNC_SEED") or 42),
        "comfyui_lipsync_timeout": int(get_setting("LLM_COMFYUI_LIPSYNC_TIMEOUT") or 2400),
        "vision_enabled": vision_enabled,
        "vision_api_url": (
            get_setting("LLM_VISION_API_URL")
            or get_setting("LLM_IMAGE_API_URL")
            if vision_enabled else ""
        ),
        "vision_api_key": (
            get_setting("LLM_VISION_API_KEY")
            or get_setting("LLM_IMAGE_API_KEY")
            if vision_enabled else ""
        ),
        "vision_model": (
            get_setting("LLM_VISION_MODEL")
            or get_setting("LLM_IMAGE_MODEL")
            or get_setting("LLM_MODEL")
        ),
        "vision_provider": get_setting("LLM_VISION_PROVIDER") or "auto",
        "vision_max_tokens": int(get_setting("LLM_VISION_MAX_TOKENS") or 1200),
        "vision_recipe_enabled": bool(get_setting("LLM_VISION_RECIPE_ENABLED")),
        "vision_pipeline_enabled": bool(get_setting("LLM_VISION_PIPELINE_ENABLED")),
        "vision_ocr_api_url": get_setting("LLM_VISION_OCR_API_URL") or "",
        "vision_ocr_model": get_setting("LLM_VISION_OCR_MODEL") or "",
        "vision_detail_api_url": get_setting("LLM_VISION_DETAIL_API_URL") or "",
        "vision_detail_model": get_setting("LLM_VISION_DETAIL_MODEL") or "",
        "vision_style_api_url": get_setting("LLM_VISION_STYLE_API_URL") or "",
        "vision_style_model": get_setting("LLM_VISION_STYLE_MODEL") or "",
        "provider": get_setting("LLM_PROVIDER"),
        "temperature": get_setting("LLM_TEMPERATURE"),
        "max_tokens": get_setting("LLM_MAX_TOKENS"),
        "stream_timeout": get_setting("LLM_STREAM_TIMEOUT"),
        "video_tool_timeout": get_setting("LLM_VIDEO_TOOL_TIMEOUT"),
        "max_iterations": get_setting("LLM_MAX_ITERATIONS"),
        "context_window": get_setting("LLM_CONTEXT_WINDOW"),
        "compaction_threshold": get_setting("LLM_COMPACTION_THRESHOLD"),
        "preserve_recent": get_setting("LLM_PRESERVE_RECENT"),
        "tool_result_max_chars": get_setting("LLM_TOOL_RESULT_MAX_CHARS"),
        "reachy": get_reachy_config(),
    }


def get_discord_config() -> dict:
    """Get current Discord integration config with overrides applied."""
    return {
        "enabled": bool(get_setting("DISCORD_ENABLED")),
        "bot_token": get_setting("DISCORD_BOT_TOKEN") or "",
        "guild_id": get_setting("DISCORD_GUILD_ID") or "",
        "channel_id": get_setting("DISCORD_CHANNEL_ID") or "",
        "poll_interval_seconds": int(get_setting("DISCORD_POLL_INTERVAL_SECONDS") or 10),
    }


def get_reachy_config() -> dict:
    """Get current Reachy Mini integration config with overrides applied."""
    return {
        "enabled": bool(get_setting("REACHY_ENABLED")),
        "thread_id": get_setting("REACHY_THREAD_ID") or "",
        "wake_word": get_setting("REACHY_WAKE_WORD") or "Reachy",
        "connection_mode": get_setting("REACHY_CONNECTION_MODE") or "",
        "media_backend": get_setting("REACHY_MEDIA_BACKEND") or "no_media",
        "task_queue": get_setting("REACHY_TASK_QUEUE") or "reachy-local",
        "speech_enabled": bool(get_setting("REACHY_SPEECH_ENABLED")),
    }


def get_redis_url() -> str:
    """Build the effective Redis URL, appending REDIS_DB if not already in the URL."""
    url = get_setting("REDIS_URL")
    db = get_setting("REDIS_DB")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.path and parsed.path not in ("", "/"):
        return url
    return f"{url.rstrip('/')}/{db}"
