import re

_IMAGE_FILENAME_LINE = re.compile(r"(?m)^image\d+\.(png|jpe?g|gif|bmp|webp)\s*$")
_IMAGE_URL = re.compile(r"https?://\S+?\.(png|jpe?g|gif|bmp|webp)(\?\S*)?", re.IGNORECASE)
_FILE_URL = re.compile(r"file:(//)?\S+", re.IGNORECASE)
_SEPARATOR_LINE = re.compile(r"(?m)^\s*[-_*=]{3,}\s*$")
_CONTROL_CHARS = re.compile(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F]")
_HTML_TAGS = re.compile(r"<[^>]+>")
_TRAILING_SPACES = re.compile(r"(?m)[ \t]+$")
_MULTI_NEWLINES = re.compile(r"\n{3,}")

_HTML_ENTITIES: dict[str, str] = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
}


class TextCleaner:
    def clean_text(self, text: str | None) -> str:
        if text is None or not text.strip():
            return ""

        t = text

        t = _CONTROL_CHARS.sub("", t)
        t = _IMAGE_FILENAME_LINE.sub("", t)
        t = _IMAGE_URL.sub("", t)
        t = _FILE_URL.sub("", t)
        t = _SEPARATOR_LINE.sub("", t)

        t = t.replace("\r\n", "\n").replace("\r", "\n")
        t = _TRAILING_SPACES.sub("", t)
        t = _MULTI_NEWLINES.sub("\n\n", t)

        return t.strip()

    def clean_text_with_limit(self, text: str | None, max_length: int) -> str:
        cleaned = self.clean_text(text)
        if len(cleaned) > max_length:
            return cleaned[:max_length]
        return cleaned

    def clean_to_single_line(self, text: str | None) -> str:
        if text is None or not text.strip():
            return ""
        return re.sub(r"\s+", " ", re.sub(r"[\r\n]+", " ", text)).strip()

    def strip_html(self, text: str | None) -> str:
        if text is None or not text.strip():
            return ""
        result = _HTML_TAGS.sub(" ", text)
        for entity, replacement in _HTML_ENTITIES.items():
            result = result.replace(entity, replacement)
        return re.sub(r"\s+", " ", result).strip()
