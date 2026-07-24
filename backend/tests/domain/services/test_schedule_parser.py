from datetime import datetime

import pytest

from app.domain.services.schedule_parser import is_valid_parse, parse_by_rules

_FEISHU = (
    "公司：字节跳动\n岗位：后端工程师\n时间：2026-08-01 14:30\n第二轮面试\n会议链接：https://meeting.feishu.cn/j/abc123"
)

_TENCENT = "腾讯会议\n公司：X公司\n岗位：Java开发\n时间：2026-08-02 10:00\n会议号：123456789\n密码：1234"

_ZOOM = "Zoom Meeting\n公司：Globex\n岗位：SRE\n2026-08-03 09:15\nhttps://zoom.us/j/9999"


class TestParseFeishu:
    def test_parses_complete_invite(self) -> None:
        result = parse_by_rules(_FEISHU, None)
        assert result is not None
        assert result.company_name == "字节跳动"
        assert result.position == "后端工程师"
        assert result.interview_time == datetime(2026, 8, 1, 14, 30)
        assert result.interview_type == "VIDEO"
        assert result.meeting_link is not None
        assert "meeting.feishu.cn" in result.meeting_link
        assert result.round_number == 2


class TestParseTencent:
    def test_parses_meeting_id_and_password(self) -> None:
        result = parse_by_rules(_TENCENT, None)
        assert result is not None
        assert result.company_name == "X公司"
        assert result.position == "Java开发"
        assert result.interview_time == datetime(2026, 8, 2, 10, 0)
        assert result.meeting_link is not None
        assert "123456789" in result.meeting_link
        assert "密码: 1234" in result.meeting_link  # 精确校验密码段，避免与会议号子串混淆


class TestParseZoom:
    def test_parses_link_and_time(self) -> None:
        result = parse_by_rules(_ZOOM, None)
        assert result is not None
        assert result.company_name == "Globex"
        assert result.position == "SRE"
        assert result.interview_time == datetime(2026, 8, 3, 9, 15)
        assert result.meeting_link is not None
        assert "zoom.us" in result.meeting_link


class TestSourceForced:
    def test_returns_partial_result_when_source_given(self) -> None:
        # source 强制平台时直接返回解析结果，即使字段不全
        result = parse_by_rules("时间：2026-08-01 09:00", "feishu")
        assert result is not None
        assert result.company_name is None
        assert result.interview_time == datetime(2026, 8, 1, 9, 0)


class TestAutoDetect:
    def test_selects_tencent_by_marker(self) -> None:
        result = parse_by_rules(_TENCENT, None)
        assert result is not None
        # 腾讯专属的 meeting_link 文本形态证明选中了腾讯解析器
        assert result.meeting_link is not None
        assert "会议号" in result.meeting_link


class TestUnparseable:
    def test_returns_none_when_no_time_and_no_source(self) -> None:
        assert parse_by_rules("公司：X\n岗位：Y", None) is None


class TestChineseRound:
    def test_converts_chinese_round_number(self) -> None:
        result = parse_by_rules(_FEISHU, "feishu")
        assert result is not None
        assert result.round_number == 2


class TestIsValidParse:
    def test_false_for_none(self) -> None:
        assert is_valid_parse(None) is False


class TestInvalidDatetime:
    def test_semantically_invalid_datetime_raises_currently(self) -> None:
        """当前行为：正则可匹配但语义非法的日期会抛 ValueError（#34 已定为钉住现状，不兜底 None）。"""
        text = "公司：X\n岗位：Y\n时间：2026-13-45 12:00\nhttps://meeting.feishu.cn/j/1"
        with pytest.raises(ValueError):
            parse_by_rules(text, "feishu")
