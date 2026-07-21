"""语音面试消息 -> QaRecord 适配单元测试。"""

from app.domain.entities.evaluation import QaRecord
from app.domain.entities.voice_interview import VoiceMessage
from app.domain.services.voice_qa_adapter import build_voice_qa_records


class TestBuildVoiceQaRecords:
    def test_pairs_question_and_answer(self) -> None:
        messages = [
            VoiceMessage(
                sequence_num=1,
                phase="TECH",
                ai_generated_text="请介绍 Spring Bean 生命周期",
                user_recognized_text="Bean 经历实例化、属性注入、初始化",
            )
        ]
        records = build_voice_qa_records(messages)
        assert records == [
            QaRecord(
                question_index=1,
                question="请介绍 Spring Bean 生命周期",
                category="TECH",
                user_answer="Bean 经历实例化、属性注入、初始化",
            )
        ]

    def test_unanswered_question_yields_none_answer(self) -> None:
        messages = [
            VoiceMessage(
                sequence_num=2,
                phase="PROJECT",
                ai_generated_text="请介绍你最熟悉的项目",
                user_recognized_text=None,
            )
        ]
        records = build_voice_qa_records(messages)
        assert len(records) == 1
        assert records[0].user_answer is None
        assert records[0].question_index == 2
        assert records[0].category == "PROJECT"

    def test_blank_answer_treated_as_unanswered(self) -> None:
        messages = [
            VoiceMessage(
                sequence_num=3,
                phase="HR",
                ai_generated_text="你的职业规划是什么？",
                user_recognized_text="   ",
            )
        ]
        records = build_voice_qa_records(messages)
        assert len(records) == 1
        assert records[0].user_answer is None

    def test_strips_whitespace_in_question_and_answer(self) -> None:
        messages = [
            VoiceMessage(
                sequence_num=1,
                phase="INTRO",
                ai_generated_text="  请自我介绍  ",
                user_recognized_text="  我是一名工程师  ",
            )
        ]
        records = build_voice_qa_records(messages)
        assert records[0].question == "请自我介绍"
        assert records[0].user_answer == "我是一名工程师"

    def test_skips_message_without_ai_question(self) -> None:
        messages = [
            VoiceMessage(
                sequence_num=1,
                phase="INTRO",
                ai_generated_text=None,
                user_recognized_text="用户独白",
            ),
            VoiceMessage(
                sequence_num=2,
                phase="INTRO",
                ai_generated_text="  ",
                user_recognized_text="另一段独白",
            ),
        ]
        records = build_voice_qa_records(messages)
        assert records == []

    def test_preserves_order_and_multiple_phases(self) -> None:
        messages = [
            VoiceMessage(sequence_num=1, phase="INTRO", ai_generated_text="Q1", user_recognized_text="A1"),
            VoiceMessage(sequence_num=2, phase="TECH", ai_generated_text="Q2", user_recognized_text=None),
            VoiceMessage(sequence_num=3, phase="HR", ai_generated_text="Q3", user_recognized_text="A3"),
        ]
        records = build_voice_qa_records(messages)
        assert [r.question_index for r in records] == [1, 2, 3]
        assert [r.category for r in records] == ["INTRO", "TECH", "HR"]
        assert records[1].user_answer is None

    def test_empty_input(self) -> None:
        assert build_voice_qa_records([]) == []
