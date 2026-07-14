import hashlib


class FileHashService:
    def calculate_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
