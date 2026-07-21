"""语音面试开场问题配置加载器：从 app/skills/voice-opening.yml 读取，按 skillId 选择开场白。

迁移自 Java VoiceInterviewProperties.OpeningConfig + buildOpeningQuestion 的三层选择：
1) skill-questions[skillId] 命中且非空 -> 用之
2) 否则 skillId ∈ algorithm-skills -> algorithm-question
3) 否则 -> backend-question（默认）
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "skills" / "voice-opening.yml"

_FALLBACK_ALGORITHM = (
    "你好，我是本场面试官。先做一道算法与数据结构热身题：请你从“哈希表/堆/栈/队列/树/图”里选两个，"
    "结合一道你熟悉的题，口述“为什么选这个结构、核心步骤、时间复杂度、空间复杂度、边界条件与反例”。"
    "本场不需要写代码，重点看你的思路和取舍。"
)
_FALLBACK_BACKEND = (
    "你好，我是本场面试官。第一个问题：请用 1 分钟介绍一个你深度参与的项目，"
    "按三点回答：业务目标、你负责的核心模块、核心技术栈。说完我会立刻追问一个关键技术决策。"
)


class OpeningQuestionLoader:
    """加载语音面试开场问题配置，惰性缓存（进程内单次读取）。"""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._loaded = False
        self._skill_questions: dict[str, str] = {}
        self._algorithm_skills: frozenset[str] = frozenset()
        self._algorithm_question = _FALLBACK_ALGORITHM
        self._backend_question = _FALLBACK_BACKEND

    async def get_opening_question(self, skill_id: str) -> str:
        """按 skillId 返回开场白（三层选择，恒返回非空字符串）。"""
        await self._ensure_loaded()
        by_skill = self._skill_questions.get(skill_id)
        if by_skill:
            return by_skill
        if skill_id in self._algorithm_skills:
            return self._algorithm_question
        return self._backend_question

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        await asyncio.to_thread(self._load_sync)
        self._loaded = True

    def _load_sync(self) -> None:
        if not self._config_path.is_file():
            logger.warning("开场问题配置不存在，使用内置默认: %s", self._config_path)
            return
        raw: Any = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        skill_questions = raw.get("skill-questions") or {}
        self._skill_questions = {str(k): str(v).strip() for k, v in skill_questions.items() if str(v).strip()}
        self._algorithm_skills = frozenset(str(s) for s in (raw.get("algorithm-skills") or []))
        algorithm_question = raw.get("algorithm-question")
        if algorithm_question and str(algorithm_question).strip():
            self._algorithm_question = str(algorithm_question).strip()
        backend_question = raw.get("backend-question")
        if backend_question and str(backend_question).strip():
            self._backend_question = str(backend_question).strip()
