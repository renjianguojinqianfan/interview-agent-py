"""语音面试对话编排纯逻辑：合并提交、句子切分、回声抑制、消息回填判定。零框架依赖。

对应 migration-plan 7B.5（回声抑制）/ 7B.6（多段 STT 合并 debounce）/ 7B.7（句子级并发）
/ 7C.2（fillLatestUnansweredQuestion 回填）的确定性逻辑；异步编排在 ws_handler.py。
"""

from app.domain.entities.voice_interview import VoiceMessage

MIN_COMMIT_CHARS = 20
"""累积用户转写达到该长度即可提交给 LLM（migration-plan 7B.6）。"""

COMMIT_DEBOUNCE_MS = 2500
"""静音防抖：距上次 final 片段超过该毫秒数即可提交（migration-plan 7B.6）。"""

ECHO_COOLDOWN_MS = 800
"""回声抑制冷却期：AI 播放结束后该毫秒窗口内丢弃麦克风输入（附录 F）。"""

MAX_AI_REPLY_CHARS = 120
"""AI 回复最大长度（附录 F）。"""

TTS_MAX_CONCURRENCY = 3
"""句子级并发 TTS 上限（附录 F）。"""

TTS_TIMEOUT_SECONDS = 8
"""单句 TTS 合成超时（附录 F）。"""

_SENTENCE_ENDINGS = frozenset("。！？!?；;\n")


def merge_segments(segments: list[str]) -> str:
    """合并已确认的 final 片段：去除首尾空白与空片段后顺序拼接。"""
    return "".join(cleaned for cleaned in (seg.strip() for seg in segments) if cleaned)


def should_commit(merged_text: str, silence_ms: float) -> bool:
    """判定累积文本是否达到提交条件：非空且（长度达标 或 静音防抖超时）。"""
    if not merged_text:
        return False
    return len(merged_text) >= MIN_COMMIT_CHARS or silence_ms >= COMMIT_DEBOUNCE_MS


def split_sentences(text: str) -> tuple[list[str], str]:
    """从流式文本中切出完整句子。

    以句末标点/换行为边界（标点随句保留），返回 (完整句列表, 剩余未成句片段)。
    完整句去除首尾空白并跳过空句；剩余片段原样返回供后续 token 继续累积。
    """
    sentences: list[str] = []
    start = 0
    for i, ch in enumerate(text):
        if ch in _SENTENCE_ENDINGS:
            segment = text[start : i + 1].strip()
            if segment:
                sentences.append(segment)
            start = i + 1
    return sentences, text[start:]


def should_drop_audio(now_ms: float, mute_until_ms: float) -> bool:
    """回声抑制：当前时间早于静音截止时间则丢弃麦克风输入。"""
    return now_ms < mute_until_ms


def find_latest_unanswered(messages: list[VoiceMessage]) -> int | None:
    """返回最近一条已提问(ai_generated_text 非空)但未作答(user_recognized_text 空)的消息下标；无则 None。

    对应 7C.2 fillLatestUnansweredQuestion：用户回答回填到最近一条未作答的 AI 提问。
    """
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        has_question = bool((message.ai_generated_text or "").strip())
        answered = bool((message.user_recognized_text or "").strip())
        if has_question and not answered:
            return i
    return None
