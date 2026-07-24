"""JSON 安全解析工具：消除 try/except + isinstance 重复模式。"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def json_loads_list(raw: str | None) -> list[Any]:
    """安全解析 JSON 列表，空或异常返回空列表。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        logger.warning("JSON 列表解析失败")
        return []


def json_loads_dict_list(raw: str | None) -> list[dict[str, Any]]:
    """安全解析 JSON 列表，仅保留 dict 元素，空或异常返回空列表。"""
    items = json_loads_list(raw)
    return [item for item in items if isinstance(item, dict)]
