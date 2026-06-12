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

## Important Defaults

The Reachy profile defaults to the external ThreadBot/Temporal/Postgres services used by the current deployment:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@192.168.69.11:5432/threadbot
TEMPORAL_HOST=192.168.69.98
TEMPORAL_PORT=7233
REACHY_DAEMON_URL=http://127.0.0.1:8000
REACHY_MEDIA_BACKEND=default
REACHY_CAMERA_MEDIA_BACKEND=local
REACHY_SPEECH_MEDIA_BACKEND=default
REACHY_TASK_QUEUE=reachy-local
TEMPORAL_PAYLOAD_CODEC_ENABLED=true
```

Override any of these in your shell or `.env` before running Compose.

## Temporal Payload Codec Key

The deployed ThreadBot cluster encrypts Temporal payloads. Local Reachy services must use the same codec key or they will fail with:

```text
Unknown payload encoding binary/encrypted
```

Load the key from Kubernetes before starting the local Reachy services:

```bash
export TEMPORAL_PAYLOAD_CODEC_ENABLED=true
export TEMPORAL_PAYLOAD_CODEC_KEY="$(kubectl -n threadbot get secret codec-encryption-key -o jsonpath='{.data.key}' | base64 -d)"
```

Alternatively, put `TEMPORAL_PAYLOAD_CODEC_KEY=...` in a local `.env` file. Do not commit that file.

The Reachy containers use host networking and privileged device access because the daemon needs direct local access to USB/media/audio hardware.
