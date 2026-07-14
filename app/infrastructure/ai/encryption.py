import base64
import hashlib
import logging
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.api.errors import BusinessException, ErrorCode

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12
_GCM_TAG_BITS = 128


class ApiKeyEncryptionService:
    def __init__(self, encryption_key: str) -> None:
        self._raw_key = encryption_key
        self._secret_key: bytes | None = None

    def _resolve_key(self) -> bytes:
        if self._secret_key is not None:
            return self._secret_key

        trimmed = self._raw_key.strip()
        if not trimmed:
            raise BusinessException(
                ErrorCode.PROVIDER_CONFIG_READ_FAILED,
                "APP_AI_CONFIG_ENCRYPTION_KEY 未配置，无法初始化 Provider API Key 加密",
            )

        try:
            decoded = base64.b64decode(trimmed)
            if len(decoded) == 32:
                self._secret_key = decoded
                return self._secret_key
        except (ValueError, UnicodeDecodeError):
            pass

        self._secret_key = hashlib.sha256(trimmed.encode("utf-8")).digest()
        return self._secret_key

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""

        try:
            key = self._resolve_key()
            nonce = secrets.token_bytes(_NONCE_BYTES)
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
            nonce_b64 = base64.b64encode(nonce).decode("ascii")
            ct_b64 = base64.b64encode(ciphertext).decode("ascii")
            return f"{nonce_b64}:{ct_b64}"
        except BusinessException:
            raise
        except Exception as e:
            raise BusinessException(
                ErrorCode.PROVIDER_CONFIG_WRITE_FAILED,
                "加密 Provider API Key 失败",
            ) from e

    def decrypt(self, combined: str) -> str:
        if not combined:
            return ""

        try:
            key = self._resolve_key()
            nonce_b64, ct_b64 = combined.split(":", 1)
            nonce = base64.b64decode(nonce_b64)
            ciphertext = base64.b64decode(ct_b64)
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except BusinessException:
            raise
        except Exception as e:
            raise BusinessException(
                ErrorCode.PROVIDER_CONFIG_READ_FAILED,
                "解密 Provider API Key 失败，请检查 APP_AI_CONFIG_ENCRYPTION_KEY",
            ) from e
