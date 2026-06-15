# Reachy Local Compose Profile

Reachy camera/media support needs the local GStreamer WebRTC plugin path that the install scripts create:

```bash
GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/x86_64-linux-gnu:/opt/gst-plugins-rs/lib64
LD_LIBRARY_PATH=/opt/gst-plugins-rs/lib64
```

The Compose `reachy` profile persists those values for the local Reachy daemon, worker, and bridge.

## Run Local Reachy Services

Start the daemon and Temporal worker only:

```bash
docker compose --profile reachy up --build reachy-daemon reachy-worker
```

Run the bridge interactively with terminal input:

```bash
docker compose --profile reachy run --rm reachy-bridge
```

Run the bridge with a real STT command:

```bash
REACHY_BRIDGE_ARGS='--stt-command "your-stt-command"' docker compose --profile reachy run --rm reachy-bridge
```

Run the bridge with Reachy's built-in microphone and local Whisper transcription:

```bash
REACHY_BRIDGE_ARGS='--voice' docker compose --profile reachy run --rm reachy-bridge
```

The built-in voice mode records from Reachy's SDK media API, transcribes locally with `faster-whisper`, then applies the same wake-word flow as typed input. By default it uses utterance mode: recording starts when speech is detected and continues until you pause for `REACHY_VOICE_UTTERANCE_END_SILENCE_SECONDS`, so normal-length questions do not need to fit in a fixed 5-second window. Say `Reachy, ...` in one phrase, or say only `Reachy` to wake him and then speak the request within the awake timeout.

Useful voice tuning variables:

```bash
REACHY_VOICE_SOURCE=reachy        # reachy or host
REACHY_VOICE_REACHY_BACKEND=alsa-release # alsa-release, alsa, sdk-release, sdk, pulse-release, or pulse
REACHY_VOICE_REACHY_ASOUNDRC=true # generate/use official reachymini_audio_src/sink aliases in container
REACHY_VOICE_REACHY_REBOOT_AUDIO=true # reboot XVF3800 once before SDK capture; workaround for all-zero USB audio
REACHY_VOICE_PULSE_SOURCE=alsa_input.usb-Pollen_Robotics_Reachy_Mini_Audio_100025004261401296-00.analog-stereo
REACHY_VOICE_INPUT_DEVICE=alsa_input.usb-046d_Brio_101_2508AP9CQ4E8-02.mono-fallback  # fallback host mic
REACHY_VOICE_MODEL=base.en        # faster-whisper model name/path
REACHY_VOICE_DEVICE=cpu           # cpu, cuda, or auto
REACHY_VOICE_COMPUTE_TYPE=int8
REACHY_VOICE_PHRASE_SECONDS=5.0
REACHY_VOICE_SILENCE_THRESHOLD=0.01
REACHY_VOICE_UTTERANCE_MODE=true
REACHY_VOICE_UTTERANCE_CHUNK_SECONDS=0.75
REACHY_VOICE_UTTERANCE_END_SILENCE_SECONDS=1.4
REACHY_VOICE_UTTERANCE_MAX_SECONDS=25.0
REACHY_VOICE_UTTERANCE_START_TIMEOUT_SECONDS=6.0
REACHY_VOICE_POST_WAKE_END_SILENCE_SECONDS=2.4
REACHY_VOICE_POST_WAKE_START_TIMEOUT_SECONDS=12.0
REACHY_VOICE_REACHY_SILENCE_FALLBACK_WINDOWS=0 # disabled; set >0 to fall back to host after silent Reachy windows
REACHY_WAKE_DETECTOR=transcript    # transcript or openwakeword
REACHY_OPENWAKEWORD_MODEL=alexa    # built-in OpenWakeWord model key
REACHY_OPENWAKEWORD_THRESHOLD=0.5
REACHY_OPENWAKEWORD_WINDOW_SECONDS=1.5
REACHY_ROBOT_SLEEP_ON_IDLE=true    # exact daemon sleep pose while waiting; daemon wake on trigger
REACHY_POST_SPEECH_SLEEP_DELAY=2.0 # seconds to stay awake after speech finishes
REACHY_OUTPUT_VOLUME=100           # daemon speaker volume set at start of each speech workflow
REACHY_RESPONSE_MOOD=helpful       # opening persona before speech starts
```

Use `REACHY_VOICE_SOURCE=host` only if you explicitly want a host microphone instead of Reachy's microphone.
Host microphone fallback is disabled by default. Set `REACHY_VOICE_REACHY_SILENCE_FALLBACK_WINDOWS` to a positive number only if you explicitly want the bridge to switch to the host microphone after that many fully silent Reachy windows.
The default `alsa-release` path asks the daemon to release media, records directly from the official `reachymini_audio_src` ALSA alias, then asks the daemon to reacquire media. This avoids the SDK media object opening the camera IPC path and prevents repeated SDK audio pipeline instances from leaving `reachymini_audio_src` busy. `sdk` and `sdk-release` are useful diagnostics for comparing against `ReachyMini.media`; `pulse` and `pulse-release` capture the Pollen USB PulseAudio/PipeWire source directly.

When Reachy hears only the wake word, the next request capture uses the post-wake timing values. The longer `REACHY_VOICE_POST_WAKE_END_SILENCE_SECONDS` prevents a short pause after saying "Reachy" from prematurely ending the request before the full prompt is spoken.

The bridge container defaults `REACHY_VOICE_REACHY_ASOUNDRC=true` and `REACHY_VOICE_REACHY_REBOOT_AUDIO=true` because official Reachy/XVF3800 reports show the Lite microphone can return all-zero samples until the XMOS audio chip is rebooted after USB connection. If audio still records all zeros after that reboot and `.asoundrc` setup, Pollen's troubleshooting docs say to inspect the microphone FPC cable: audio returning zeros can mean the cable is plugged upside down or damaged.

The Hugging Face `fcollonval/reachy_mini_wake_word` Space uses OpenWakeWord. To use the same style locally, set `REACHY_WAKE_DETECTOR=openwakeword`. The Space does not include a custom `Reachy` model; by default this uses OpenWakeWord's built-in `alexa` model, so say `Alexa`, wait for the request prompt, then speak the request. Continue using `REACHY_WAKE_DETECTOR=transcript` for the normal `Reachy, ...` phrase flow.

By default, the bridge also keeps Reachy in the SDK/daemon sleep pose while waiting for input and wakes him when the wake word or OpenWakeWord trigger is detected. This uses the same daemon `goto_sleep` routine used on daemon shutdown: speech wobble is disabled, speech offsets are cleared, the robot optionally returns through init pose, `go_sleep.wav` plays, and the head/antennae move to the daemon sleep pose. Set `REACHY_ROBOT_SLEEP_ON_IDLE=false` to keep the previous always-awake posture behavior.

When a prompt is being processed, ThreadBot loops the `thoughtful` persona until response text starts. Each reply starts with `REACHY_RESPONSE_MOOD` (default `helpful`) and then loops `yeah_nod` while Reachy is audibly speaking. These loops run complete animation cycles and only restart after a cycle completes; no animation runs while Reachy is asleep.

Supported persona names include `loving`, `grateful`, `helpful`, `surprised`, `thoughtful`, `yes`, `no`, `boredom`, `anxiety`, `downcast`, `sad`, `reprimand`, `fear`, `exhausted`, `relief`, and `dance`. The speaking persona aliases `talking`, `speaking`, `yeah_nod`, and `yeah nod` all play the `yeah_nod` recorded move.

## Important Defaults

The Reachy profile defaults to the external ThreadBot/Temporal/Postgres services used by the current deployment:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@192.168.69.11:5432/threadbot
TEMPORAL_HOST=192.168.69.98
TEMPORAL_PORT=7233
REACHY_DAEMON_URL=http://127.0.0.1:8000
REACHY_MEDIA_BACKEND=default
REACHY_CAMERA_MEDIA_BACKEND=local
REACHY_CAMERA_CAPTURE_MODE=ffmpeg
REACHY_CAMERA_DEVICE=
REACHY_SPEECH_MEDIA_BACKEND=default
REACHY_TASK_QUEUE=reachy-local
TEMPORAL_PAYLOAD_CODEC_ENABLED=false
```

Override any of these in your shell or `.env` before running Compose.

Camera capture defaults to `ffmpeg` because it is more reliable in Docker than the Reachy SDK frame client. If auto-detection picks the wrong camera, set `REACHY_CAMERA_DEVICE` to the Reachy device path, for example:

```bash
REACHY_CAMERA_DEVICE=/dev/v4l/by-id/usb-SunplusIT_Inc_Reachy_Mini_Camera_J20251118V0-video-index0
```

The profile also shares a `reachy-tmp` volume at `/tmp` across Reachy services. Speech writes generated WAV files there and asks the daemon to play them via `/api/media/play_sound`.

## Temporal Payload Codec Key

The Reachy Compose profile defaults `TEMPORAL_PAYLOAD_CODEC_ENABLED=false` so local testing works without a codec key. If your deployed ThreadBot workers encode Temporal payloads, local Reachy services must use the same codec key or they can fail with:

```text
Unknown payload encoding binary/encrypted
```

Load the key from Kubernetes and enable the codec before starting the local Reachy services:

```bash
export TEMPORAL_PAYLOAD_CODEC_ENABLED=true
export TEMPORAL_PAYLOAD_CODEC_KEY="$(kubectl -n threadbot get secret codec-encryption-key -o jsonpath='{.data.key}' | base64 -d)"
```

Alternatively, put `TEMPORAL_PAYLOAD_CODEC_KEY=...` in a local `.env` file. Do not commit that file.

The Reachy containers use host networking and privileged device access because the daemon needs direct local access to USB/media/audio hardware.
