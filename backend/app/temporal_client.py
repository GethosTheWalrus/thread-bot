import base64
import dataclasses
import os
from typing import Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from temporalio.api.common.v1 import Payload
from temporalio.client import Client
from temporalio.converter import PayloadCodec
import temporalio.converter

from app.config import get_settings


ENCRYPTED_ENCODING = b"binary/encrypted"


class AesGcmPayloadCodec(PayloadCodec):
    """Temporal payload codec compatible with the cluster codec-server key."""

    def __init__(self, key: bytes) -> None:
        self._aesgcm = AESGCM(key)

    async def encode(self, payloads: Iterable[Payload]) -> list[Payload]:
        encoded = []
        for payload in payloads:
            nonce = os.urandom(12)
            ciphertext = self._aesgcm.encrypt(nonce, payload.SerializeToString(), None)
            encoded.append(Payload(
                metadata={"encoding": ENCRYPTED_ENCODING},
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
            decoded.append(Payload.FromString(self._aesgcm.decrypt(nonce, ciphertext, None)))
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


async def connect_temporal_client() -> Client:
    settings = get_settings()
    data_converter = get_temporal_data_converter()
    kwargs = {}
    if data_converter is not None:
        kwargs["data_converter"] = data_converter
    return await Client.connect(
        target_host=f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
        **kwargs,
    )
