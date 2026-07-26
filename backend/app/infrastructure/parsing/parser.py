import logging
from io import BytesIO
from typing import Any

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.parsing.content_type import ContentTypeDetector
from app.infrastructure.parsing.text_cleaner import TextCleaner

logger = logging.getLogger(__name__)

_MAX_TEXT_LENGTH = 5 * 1024 * 1024


def _partition_pdf(data: bytes) -> list[Any]:
    # #51：unstructured 0.21+ 的 partition.pdf 模块 import 即硬依赖 unstructured-inference
    # （拉取 torch 约 2GB），而本项目仅需纯文本抽取。改用 pdfminer.six（unstructured[pdf]
    # 既有传递依赖，与其 fast 策略同源）；扫描件无文本层时抽取为空，由上游空文本校验报错
    from pdfminer.high_level import extract_text

    text = extract_text(BytesIO(data))
    return [text] if text.strip() else []


def _partition_docx(data: bytes) -> list[Any]:
    from unstructured.partition.docx import partition_docx

    return partition_docx(file=BytesIO(data))


class DocumentParser:
    def __init__(self, text_cleaner: TextCleaner) -> None:
        self._text_cleaner = text_cleaner
        self._detector = ContentTypeDetector()

    def parse_content(self, data: bytes, filename: str) -> str:
        if not data:
            logger.warning("文件为空: %s", filename)
            return ""

        try:
            content_type = self._detector.detect(data, filename)
            if self._detector.is_plain_text(content_type) or self._detector.is_markdown(content_type, filename):
                raw = data.decode("utf-8", errors="replace")
            elif self._detector.is_pdf(content_type):
                elements = _partition_pdf(data)
                raw = "\n\n".join(str(el) for el in elements)
            elif self._detector.is_word_document(content_type):
                elements = _partition_docx(data)
                raw = "\n\n".join(str(el) for el in elements)
            else:
                logger.warning("不支持的文件类型: %s (%s)", filename, content_type)
                raw = data.decode("utf-8", errors="replace")

            cleaned = self._text_cleaner.clean_text(raw)
            if len(cleaned) > _MAX_TEXT_LENGTH:
                cleaned = cleaned[:_MAX_TEXT_LENGTH]
            logger.info("文件解析成功: %s, 提取文本长度: %d 字符", filename, len(cleaned))
            return cleaned
        except BusinessException:
            raise
        except Exception as e:
            logger.error("文件解析失败: %s, error=%s", filename, e)
            raise BusinessException(
                ErrorCode.INTERNAL_ERROR,
                f"文件解析失败: {e}",
            ) from e
