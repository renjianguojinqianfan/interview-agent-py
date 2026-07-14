import base64
import hashlib

import pytest

from app.api.errors import BusinessException, ErrorCode
from app.infrastructure.ai.encryption import ApiKeyEncryptionService


@pytest.fixture()
def encryption_key() -> str:
    return "test-encryption-key-for-unit-tests"


@pytest.fixture()
def service(encryption_key: str) -> ApiKeyEncryptionService:
    return ApiKeyEncryptionService(encryption_key)


class TestApiKeyEncryptionServiceEncryptDecrypt:
    def test_round_trip_returns_original_plaintext(self, service: ApiKeyEncryptionService) -> None:
        plaintext = "sk-abcdefghijklmn0123456789"
        encrypted = service.encrypt(plaintext)
        assert encrypted != plaintext
        assert service.decrypt(encrypted) == plaintext

    def test_encrypt_returns_nonce_ciphertext_format(self, service: ApiKeyEncryptionService) -> None:
        encrypted = service.encrypt("my-secret-key")
        parts = encrypted.split(":")
        assert len(parts) == 2
        nonce_bytes = base64.b64decode(parts[0])
        assert len(nonce_bytes) == 12

    def test_each_encryption_produces_different_ciphertext(self, service: ApiKeyEncryptionService) -> None:
        plaintext = "same-key"
        enc1 = service.encrypt(plaintext)
        enc2 = service.encrypt(plaintext)
        assert enc1 != enc2
        assert service.decrypt(enc1) == plaintext
        assert service.decrypt(enc2) == plaintext

    def test_encrypt_empty_string_returns_empty(self, service: ApiKeyEncryptionService) -> None:
        assert service.encrypt("") == ""

    def test_decrypt_empty_string_returns_empty(self, service: ApiKeyEncryptionService) -> None:
        assert service.decrypt("") == ""

    def test_decrypt_tampered_ciphertext_raises(self, service: ApiKeyEncryptionService) -> None:
        encrypted = service.encrypt("secret")
        nonce_b64, _ = encrypted.split(":")
        tampered = f"{nonce_b64}:{base64.b64encode(b'tampered').decode()}"
        with pytest.raises(BusinessException) as exc_info:
            service.decrypt(tampered)
        assert exc_info.value.error_code == ErrorCode.PROVIDER_CONFIG_READ_FAILED


class TestApiKeyEncryptionServiceKeyResolution:
    def test_base64_encoded_32_byte_key_used_directly(self) -> None:
        raw_key = b"\x00" * 32
        b64_key = base64.b64encode(raw_key).decode()
        service = ApiKeyEncryptionService(b64_key)
        plaintext = "test-key"
        encrypted = service.encrypt(plaintext)
        assert service.decrypt(encrypted) == plaintext

    def test_human_readable_key_sha256_derived(self, encryption_key: str) -> None:
        service = ApiKeyEncryptionService(encryption_key)
        service.encrypt("trigger-key-resolution")
        expected_key = hashlib.sha256(encryption_key.encode("utf-8")).digest()
        assert service._secret_key == expected_key

    def test_empty_key_raises_on_encrypt(self) -> None:
        service = ApiKeyEncryptionService("")
        with pytest.raises(BusinessException) as exc_info:
            service.encrypt("test")
        assert exc_info.value.error_code == ErrorCode.PROVIDER_CONFIG_READ_FAILED

    def test_empty_key_raises_on_decrypt(self) -> None:
        service = ApiKeyEncryptionService("")
        with pytest.raises(BusinessException) as exc_info:
            service.decrypt("dGVzdA==:dGVzdA==")
        assert exc_info.value.error_code == ErrorCode.PROVIDER_CONFIG_READ_FAILED

    def test_whitespace_only_key_raises(self) -> None:
        service = ApiKeyEncryptionService("   ")
        with pytest.raises(BusinessException):
            service.encrypt("test")
