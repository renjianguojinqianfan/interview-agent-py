"""技能知识检索 Tool：语音面试对话中 LLM 可自主调用以查阅参考资料。

对标 Java 版 SkillsTool（spring-ai-agent-utils），Python 实现用 LangChain @tool。
工具执行为本地文件读取（<10ms），不涉及 LLM 调用。
"""

import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "skills"
_SHARED_REFERENCES = _SKILLS_ROOT / "_shared" / "references"


def _load_skill_reference(skill_id: str, category: str) -> str:
    """加载技能参考资料文件内容。

    查找策略：
    1. skills/{skill_id}/_shared/references/ 下按 category 匹配（如 java.md）
    2. skills/_shared/references/ 全局共享目录
    3. skills/{skill_id}/SKILL.md 作为兜底
    """
    # 规范化 category 到文件名（如 JAVA -> java.md, MYSQL -> mysql.md）
    filename = category.lower().replace("_", "-") + ".md"

    # 策略 1: 技能目录下的引用
    skill_ref = _SKILLS_ROOT / skill_id / filename
    if skill_ref.exists():
        return _read_and_truncate(skill_ref)

    # 策略 2: 全局共享引用
    shared_ref = _SHARED_REFERENCES / filename
    if shared_ref.exists():
        return _read_and_truncate(shared_ref)

    # 策略 3: SKILL.md 兜底
    skill_md = _SKILLS_ROOT / skill_id / "SKILL.md"
    if skill_md.exists():
        return _read_and_truncate(skill_md)

    return f"未找到 {skill_id}/{category} 的参考资料"


def _read_and_truncate(path: Path, max_chars: int = 3000) -> str:
    """读取文件并截断到 max_chars。"""
    try:
        content = path.read_text(encoding="utf-8")
        if len(content) > max_chars:
            return content[:max_chars] + "\n...(内容过长已截断)"
        return content
    except Exception as e:
        logger.warning("读取参考资料失败: path=%s, error=%s", path, e)
        return f"文件读取失败: {e}"


@tool
def lookup_skill_knowledge(skill_id: str, category: str, query: str = "") -> str:
    """检索面试技能参考资料。当你需要了解某个技术方向的深入细节以出更好的追问时调用。

    Args:
        skill_id: 技能标识（如 java-backend, python-backend, frontend）
        category: 方向标识（如 JAVA, MYSQL, REDIS, SPRING, SYSTEM_DESIGN_SCENARIO）
        query: 可选的具体查询（当前版本不做语义过滤，直接返回全文）
    """
    return _load_skill_reference(skill_id, category)


# 导出供 AgentDialogueLlm 绑定
SKILL_TOOLS = [lookup_skill_knowledge]
