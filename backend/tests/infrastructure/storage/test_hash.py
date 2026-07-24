import hashlib

from app.infrastructure.storage.hash import FileHashService


class TestCalculateHash:
    def test_returns_sha256_hex(self) -> None:
        service = FileHashService()
        result = service.calculate_hash(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert result == expected
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_bytes_returns_known_hash(self) -> None:
        service = FileHashService()
        result = service.calculate_hash(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_same_content_same_hash(self) -> None:
        service = FileHashService()
        h1 = service.calculate_hash(b"same content")
        h2 = service.calculate_hash(b"same content")
        assert h1 == h2

    def test_different_content_different_hash(self) -> None:
        service = FileHashService()
        h1 = service.calculate_hash(b"content1")
        h2 = service.calculate_hash(b"content2")
        assert h1 != h2

    def test_large_content(self) -> None:
        service = FileHashService()
        data = b"x" * 100_000
        result = service.calculate_hash(data)
        expected = hashlib.sha256(data).hexdigest()
        assert result == expected
