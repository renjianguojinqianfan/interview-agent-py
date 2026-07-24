"""OpeningQuestionLoader 单元测试：三层选择逻辑、缺失兜底、缓存。"""

from pathlib import Path

from app.infrastructure.skills.opening_loader import _FALLBACK_BACKEND, OpeningQuestionLoader

_SAMPLE = """\
skill-questions:
  java-backend: JB 开场
algorithm-skills:
  - algorithm
  - bytedance-backend
algorithm-question: ALGO 开场
backend-question: BACKEND 开场
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "voice-opening.yml"
    path.write_text(content, encoding="utf-8")
    return path


async def test_skill_specific_hit(tmp_path: Path) -> None:
    loader = OpeningQuestionLoader(config_path=_write(tmp_path, _SAMPLE))
    assert await loader.get_opening_question("java-backend") == "JB 开场"


async def test_algorithm_skill_fallback(tmp_path: Path) -> None:
    loader = OpeningQuestionLoader(config_path=_write(tmp_path, _SAMPLE))
    # algorithm 不在 skill-questions，但属于 algorithm-skills -> algorithm-question
    assert await loader.get_opening_question("algorithm") == "ALGO 开场"


async def test_backend_question_default(tmp_path: Path) -> None:
    loader = OpeningQuestionLoader(config_path=_write(tmp_path, _SAMPLE))
    assert await loader.get_opening_question("unknown-skill") == "BACKEND 开场"


async def test_missing_file_uses_builtin_fallback(tmp_path: Path) -> None:
    loader = OpeningQuestionLoader(config_path=tmp_path / "nope.yml")
    assert await loader.get_opening_question("anything") == _FALLBACK_BACKEND


async def test_real_config_returns_nonempty_for_known_skills() -> None:
    loader = OpeningQuestionLoader()
    for skill_id in ("java-backend", "bytedance-backend", "frontend", "ai-agent-dev"):
        question = await loader.get_opening_question(skill_id)
        assert isinstance(question, str) and question.strip()


async def test_caches_after_first_load(tmp_path: Path) -> None:
    config = _write(tmp_path, _SAMPLE)
    loader = OpeningQuestionLoader(config_path=config)
    assert await loader.get_opening_question("java-backend") == "JB 开场"
    config.write_text("skill-questions:\n  java-backend: CHANGED\n", encoding="utf-8")
    # 已缓存，不重新读取磁盘
    assert await loader.get_opening_question("java-backend") == "JB 开场"
