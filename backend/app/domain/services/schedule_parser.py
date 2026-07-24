"""面试邀约规则解析：纯函数，零框架依赖。

覆盖飞书/腾讯会议/Zoom 三大平台的正则解析。
接收 raw_text 字符串，返回 ParsedSchedule dataclass。
"""

import re
from datetime import datetime

from app.domain.entities.interview_schedule import ParsedSchedule

# ==================== 规则解析正则 ====================

_TIME_PATTERN_FEISHU = re.compile(r"(?:时间|时段)[：:]\s*(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2})")
_LINK_PATTERN_FEISHU = re.compile(r"https://meeting\.feishu\.cn/[^\s\n]+")
_COMPANY_PATTERN = re.compile(r"(?:公司|单位|组织)[：:]\s*([^\s\n]{1,50})")
_POSITION_PATTERN = re.compile(r"(?:岗位|职位|职务)[：:]\s*([^\s\n]{1,50})")
_ROUND_PATTERN_FEISHU = re.compile(r"第\s*([一二三四五六七八九十\d]+)\s*[轮场]")

_TIME_PATTERN_TENCENT = re.compile(r"(\d{4}[-/]\d{2}[-/]\d{2})\s+(\d{2}:\d{2})")
_MEETING_ID_PATTERN_TENCENT = re.compile(r"(?:会议号|ID)[：:]?\s*(\d{9,})")
_PASSWORD_PATTERN_TENCENT = re.compile(r"密码[：:]?\s*(\d{4,})")

_LINK_PATTERN_ZOOM = re.compile(r"https://zoom\.us/j/[^\s\n]+")
_DATE_PATTERN_ZOOM = re.compile(r"(\d{4}[-/]\d{2}[-/]\d{2})")
_HOUR_PATTERN_ZOOM = re.compile(r"(\d{1,2}:\d{2})")

_CHINESE_NUMBERS: dict[str, int] = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_by_rules(raw_text: str, source: str | None) -> ParsedSchedule | None:
    """规则解析入口：按 source 或自动检测选择平台解析器。

    返回 None 表示无法解析，ParsedSchedule（含 None 字段）表示部分解析。
    """
    if source is not None:
        source_lower = source.lower()
        if source_lower == "feishu":
            return _parse_feishu(raw_text)
        if source_lower == "tencent":
            return _parse_tencent(raw_text)
        if source_lower == "zoom":
            return _parse_zoom(raw_text)

    if "飞书" in raw_text or "Feishu" in raw_text or "meeting.feishu.cn" in raw_text:
        result = _parse_feishu(raw_text)
        if is_valid_parse(result):
            return result

    if "腾讯会议" in raw_text or "Tencent Meeting" in raw_text or "会议号" in raw_text:
        result = _parse_tencent(raw_text)
        if is_valid_parse(result):
            return result

    if "Zoom" in raw_text or "zoom.us" in raw_text:
        result = _parse_zoom(raw_text)
        if is_valid_parse(result):
            return result

    for parser in (_parse_feishu, _parse_tencent, _parse_zoom):
        result = parser(raw_text)
        if is_valid_parse(result):
            return result

    return None


def is_valid_parse(result: ParsedSchedule | None) -> bool:
    """检查解析结果是否包含三个必需字段。"""
    if result is None:
        return False
    return result.company_name is not None and result.position is not None and result.interview_time is not None


def _parse_feishu(raw_text: str) -> ParsedSchedule:
    time_match = _TIME_PATTERN_FEISHU.search(raw_text)
    interview_time = _parse_datetime(time_match.group(1)) if time_match else None

    link_match = _LINK_PATTERN_FEISHU.search(raw_text)
    meeting_link = link_match.group() if link_match else None

    company_match = _COMPANY_PATTERN.search(raw_text)
    company_name = company_match.group(1).strip() if company_match else None

    position_match = _POSITION_PATTERN.search(raw_text)
    position = position_match.group(1).strip() if position_match else None

    round_match = _ROUND_PATTERN_FEISHU.search(raw_text)
    round_number = _parse_round_number(round_match.group(1)) if round_match else 1

    return ParsedSchedule(
        company_name=company_name,
        position=position,
        interview_time=interview_time,
        interview_type="VIDEO",
        meeting_link=meeting_link,
        round_number=round_number,
    )


def _parse_tencent(raw_text: str) -> ParsedSchedule:
    time_match = _TIME_PATTERN_TENCENT.search(raw_text)
    interview_time = None
    if time_match:
        time_str = f"{time_match.group(1)} {time_match.group(2)}"
        interview_time = _parse_datetime(time_str)

    meeting_id_match = _MEETING_ID_PATTERN_TENCENT.search(raw_text)
    password_match = _PASSWORD_PATTERN_TENCENT.search(raw_text)
    meeting_link = None
    parts: list[str] = []
    if meeting_id_match:
        parts.append(f"会议号: {meeting_id_match.group(1)}")
    if password_match:
        parts.append(f"密码: {password_match.group(1)}")
    if parts:
        meeting_link = " ".join(parts)

    company_match = _COMPANY_PATTERN.search(raw_text)
    company_name = company_match.group(1).strip() if company_match else None

    position_match = _POSITION_PATTERN.search(raw_text)
    position = position_match.group(1).strip() if position_match else None

    return ParsedSchedule(
        company_name=company_name,
        position=position,
        interview_time=interview_time,
        interview_type="VIDEO",
        meeting_link=meeting_link,
    )


def _parse_zoom(raw_text: str) -> ParsedSchedule:
    link_match = _LINK_PATTERN_ZOOM.search(raw_text)
    meeting_link = link_match.group() if link_match else None

    date_match = _DATE_PATTERN_ZOOM.search(raw_text)
    hour_match = _HOUR_PATTERN_ZOOM.search(raw_text)
    interview_time = None
    if date_match and hour_match:
        time_str = f"{date_match.group(1)} {hour_match.group(1)}"
        interview_time = _parse_datetime(time_str)

    company_match = _COMPANY_PATTERN.search(raw_text)
    company_name = company_match.group(1).strip() if company_match else None

    position_match = _POSITION_PATTERN.search(raw_text)
    position = position_match.group(1).strip() if position_match else None

    return ParsedSchedule(
        company_name=company_name,
        position=position,
        interview_time=interview_time,
        interview_type="VIDEO",
        meeting_link=meeting_link,
    )


def _parse_datetime(time_str: str) -> datetime:
    normalized = time_str.replace("/", "-")
    if len(normalized) == 16:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M")
    if len(normalized) == 19:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
    return datetime.fromisoformat(normalized)


def _parse_round_number(text: str) -> int:
    text = text.strip()
    if text.isdigit():
        return int(text)
    for char in text:
        if char in _CHINESE_NUMBERS:
            return _CHINESE_NUMBERS[char]
        if char.isdigit():
            return int(char)
    return 1
