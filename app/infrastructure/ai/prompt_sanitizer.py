import logging
import re
import uuid

logger = logging.getLogger(__name__)

_ROLE_INJECTION_PATTERN = re.compile(r"(?im)^\s*(system|user|assistant|human|ai|model)\s*[:：].*")

_INJECTION_PHRASE_PATTERN = re.compile(
    r"(ignore\s+(previous|above|all|your)\s*(instructions|prompts|rules))"
    r"|(forget\s+(everything|all\s*(previous\s*)?(instructions|rules|prompts)))"
    r"|(new\s+instructions?:)"
    r"|忽略之前的指令"
    r"|忘记之前的指令"
    r"|忽略以上所有"
    r"|你不再是"
    r"|你的新角色是",
    re.IGNORECASE,
)

_DELIMITER_INJECTION_PATTERN = re.compile(r"---(?:简历|文档|问答)内容(?:开始|结束)---")

_BOUNDARY_TAG_PATTERN = re.compile(r"</?data-boundary[^>]*>", re.IGNORECASE)


class PromptSanitizer:
    def sanitize(self, text: str | None) -> str | None:
        if text is None or not text:
            return text

        result = text
        injected = False

        role_matcher = _ROLE_INJECTION_PATTERN.search(result)
        if role_matcher:
            injected = True
            result = _ROLE_INJECTION_PATTERN.sub("[filtered-role-marker]", result)

        phrase_matcher = _INJECTION_PHRASE_PATTERN.search(result)
        if phrase_matcher:
            injected = True
            result = _INJECTION_PHRASE_PATTERN.sub("[filtered]", result)

        delim_matcher = _DELIMITER_INJECTION_PATTERN.search(result)
        if delim_matcher:
            result = _DELIMITER_INJECTION_PATTERN.sub("[filtered-delimiter]", result)

        tag_matcher = _BOUNDARY_TAG_PATTERN.search(result)
        if tag_matcher:
            result = _BOUNDARY_TAG_PATTERN.sub("[filtered-boundary-tag]", result)

        if injected:
            logger.warning("检测到 Prompt 注入尝试，已清洗: len=%d", len(text))

        return result

    def wrap_with_delimiters(self, label: str, text: str) -> str:
        short_id = uuid.uuid4().hex[:8]
        open_tag = f"<data-boundary-{short_id}-{label}>"
        close_tag = f"</data-boundary-{short_id}-{label}>"
        return f"{open_tag}\n{text}\n{close_tag}"

    def detect_injection_attempt(self, text: str | None) -> bool:
        if text is None or not text:
            return False
        return bool(_ROLE_INJECTION_PATTERN.search(text) or _INJECTION_PHRASE_PATTERN.search(text))
