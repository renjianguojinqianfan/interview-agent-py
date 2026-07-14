import filetype  # type: ignore[import-untyped]


class ContentTypeDetector:
    def detect(self, data: bytes, filename: str | None = None) -> str:
        if data:
            kind = filetype.guess(data)
            if kind is not None:
                return str(kind.mime)
        if filename:
            ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
            ext_map = {
                "pdf": "application/pdf",
                "doc": "application/msword",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "txt": "text/plain",
                "md": "text/markdown",
                "markdown": "text/markdown",
            }
            if ext in ext_map:
                return ext_map[ext]
        return "application/octet-stream"

    def is_pdf(self, content_type: str | None) -> bool:
        return content_type is not None and "pdf" in content_type.lower()

    def is_word_document(self, content_type: str | None) -> bool:
        if content_type is None:
            return False
        lower = content_type.lower()
        return "msword" in lower or "wordprocessingml" in lower

    def is_plain_text(self, content_type: str | None) -> bool:
        return content_type is not None and content_type.lower().startswith("text/")

    def is_markdown(self, content_type: str | None, filename: str | None) -> bool:
        if content_type is not None:
            lower = content_type.lower()
            if "markdown" in lower or "x-markdown" in lower:
                return True
        if filename is not None:
            lower_name = filename.lower()
            return lower_name.endswith(".md") or lower_name.endswith(".markdown")
        return False

    def is_allowed(self, content_type: str | None) -> bool:
        return (
            self.is_pdf(content_type)
            or self.is_word_document(content_type)
            or self.is_plain_text(content_type)
            or self.is_markdown(content_type, None)
        )
