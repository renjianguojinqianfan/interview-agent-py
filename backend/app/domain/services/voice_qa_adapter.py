"""语音面试消息 -> QaRecord 适配：纯函数，零框架依赖。

将 VoiceMessage（pair-per-row：ai_generated_text 为题、user_recognized_text 为答）
适配为统一评估服务所需的 QaRecord。user_answer 为 None 表示未作答（按 0 分处理）。
"""

from app.domain.entities.evaluation import QaRecord
from app.domain.entities.voice_interview import VoiceMessage


def build_voice_qa_records(messages: list[VoiceMessage]) -> list[QaRecord]:
    """将语音消息列表转换为评估用 QaRecord 列表。

    - 跳过 ai_generated_text 为空的消息（无 AI 提问，不可评估）。
    - user_recognized_text 为空或纯空白视为未作答（None）。
    - 保留原始顺序与 sequence_num 作为 question_index。
    """
    records: list[QaRecord] = []
    for msg in messages:
        question = (msg.ai_generated_text or "").strip()
        if not question:
            continue
        answer = msg.user_recognized_text
        if answer is not None:
            answer = answer.strip()
            if not answer:
                answer = None
        records.append(
            QaRecord(
                question_index=msg.sequence_num,
                question=question,
                category=msg.phase,
                user_answer=answer,
            )
        )
    return records
