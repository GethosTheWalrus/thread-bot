import base64
import dataclasses
import os
from typing import Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.protobuf.message import DecodeError
from temporalio.api.common.v1 import Payload
from temporalio.client import Client
from temporalio.converter import PayloadCodec
import temporalio.converter

from app.config import get_settings


ENCRYPTED_ENCODING = b"binary/encrypted"
ORIGINAL_ENCODING_METADATA_KEY = "encryption-original-encoding"
LEGACY_ORIGINAL_ENCODING_METADATA_KEY = "original_encoding"
DEFAULT_DECODED_ENCODING = b"json/plain"


class AesGcmPayloadCodec(PayloadCodec):
    """Temporal payload codec compatible with the cluster codec-server key."""

    def __init__(self, key: bytes) -> None:
        self._aesgcm = AESGCM(key)

    async def encode(self, payloads: Iterable[Payload]) -> list[Payload]:
        encoded = []
        for payload in payloads:
            nonce = os.urandom(12)
            ciphertext = self._aesgcm.encrypt(nonce, payload.data, None)
            metadata = {"encoding": ENCRYPTED_ENCODING}
            original_encoding = payload.metadata.get("encoding")
            if original_encoding:
                metadata[ORIGINAL_ENCODING_METADATA_KEY] = original_encoding
            encoded.append(Payload(
                metadata=metadata,
                data=nonce + ciphertext,
            ))
        return encoded

    async def decode(self, payloads: Iterable[Payload]) -> list[Payload]:
        decoded = []
        for payload in payloads:
            if payload.metadata.get("encoding") != ENCRYPTED_ENCODING:
                decoded.append(payload)
                continue
            nonce = payload.data[:12]
            ciphertext = payload.data[12:]
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            try:
                # Backward compatibility for histories written before ThreadBot
                # matched the cluster codec-server's data-only encryption format.
                decoded_payload = Payload.FromString(plaintext)
                if decoded_payload.metadata or decoded_payload.data:
                    decoded.append(decoded_payload)
                    continue
            except DecodeError:
                pass

            decoded.append(Payload(
                metadata={
                    "encoding": (
                        payload.metadata.get(ORIGINAL_ENCODING_METADATA_KEY)
                        or payload.metadata.get(LEGACY_ORIGINAL_ENCODING_METADATA_KEY)
                        or DEFAULT_DECODED_ENCODING
                    ),
                },
                data=plaintext,
            ))
        return decoded


def _read_codec_key() -> bytes:
    settings = get_settings()
    raw_key = settings.TEMPORAL_PAYLOAD_CODEC_KEY.strip()
    if not raw_key and settings.TEMPORAL_PAYLOAD_CODEC_KEY_FILE:
        with open(settings.TEMPORAL_PAYLOAD_CODEC_KEY_FILE, "r", encoding="utf-8") as f:
            raw_key = f.read().strip()
    if not raw_key:
        raise RuntimeError("TEMPORAL_PAYLOAD_CODEC_ENABLED is true but no codec key is configured")

    for candidate in (raw_key, raw_key.replace("-", "+").replace("_", "/")):
        try:
            key = base64.b64decode(candidate, validate=True)
            if len(key) in (16, 24, 32):
                return key
        except Exception:
            pass

    key = raw_key.encode("utf-8")
    if len(key) in (16, 24, 32):
        return key
    raise RuntimeError("Temporal payload codec key must decode to 16, 24, or 32 bytes")


def get_temporal_data_converter():
    settings = get_settings()
    if not settings.TEMPORAL_PAYLOAD_CODEC_ENABLED:
        return None
    return dataclasses.replace(
        temporalio.converter.default(),
        payload_codec=AesGcmPayloadCodec(_read_codec_key()),
    )


async def connect_temporal_client(**kwargs) -> Client:
    settings = get_settings()
    data_converter = get_temporal_data_converter()
    if data_converter is not None:
        kwargs["data_converter"] = data_converter

    address = os.environ.get("TEMPORAL_ADDRESS")
    if address:
        target_host = address
    else:
        target_host = f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}"

    return await Client.connect(
        target_host=target_host,
        namespace=settings.TEMPORAL_NAMESPACE,
        **kwargs,
    )


def build_worker_versioning_config():
    """Build WorkerDeploymentConfig from controller-injected env vars, or None.

    The Temporal Worker Controller (deployed in the cluster) sets
    TEMPORAL_DEPLOYMENT_NAME and TEMPORAL_WORKER_BUILD_ID on every worker
    Pod. When both are present, the worker should register itself as a
    versioned deployment so the controller can track version health and
    safely drain old versions.
    """
    deployment_name = os.environ.get("TEMPORAL_DEPLOYMENT_NAME")
    build_id = os.environ.get("TEMPORAL_WORKER_BUILD_ID")
    if not deployment_name or not build_id:
        return None
    from temporalio.common import VersioningBehavior
    from temporalio.worker import WorkerDeploymentConfig, WorkerDeploymentVersion
    return WorkerDeploymentConfig(
        version=WorkerDeploymentVersion(
            deployment_name=deployment_name,
            build_id=build_id,
        ),
        use_worker_versioning=True,
        default_versioning_behavior=VersioningBehavior.PINNED,
    )


def get_worker_build_id() -> str | None:
    return os.environ.get("TEMPORAL_WORKER_BUILD_ID")
