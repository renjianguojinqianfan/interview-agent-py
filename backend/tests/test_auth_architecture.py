"""认证架构守卫（HARD #1 防复发）。

全部业务 HTTP router 必须接入 Depends(get_current_user)；豁免 auth（login 免认证）
与 voice_ws（WS 本轮不认证，docs 标注边界）。新增业务 router 未接入即失败。
"""

from app.api.deps import get_current_user
from app.api.routers import (
    agent_interview,
    agent_rag,
    auth,
    interview,
    interview_schedule,
    knowledgebase,
    knowledgebase_interview,
    llm_provider,
    rag_chat,
    resume,
    skill,
    voice_interview,
    voice_ws,
)

PROTECTED_ROUTERS = [
    agent_interview.router,
    agent_rag.router,
    interview.router,
    interview_schedule.router,
    knowledgebase.router,
    knowledgebase_interview.router,
    llm_provider.router,
    rag_chat.router,
    resume.router,
    skill.router,
    voice_interview.router,
]

EXEMPT_ROUTERS = [auth.router, voice_ws.router]


def test_business_routers_all_require_authentication() -> None:
    for router in PROTECTED_ROUTERS:
        assert any(dep.dependency is get_current_user for dep in router.dependencies), (
            f"{router.prefix or router.tags} 未接入 Depends(get_current_user)"
        )


def test_exempt_routers_do_not_require_authentication() -> None:
    for router in EXEMPT_ROUTERS:
        assert not any(dep.dependency is get_current_user for dep in router.dependencies), (
            f"{router.prefix or router.tags} 不应接入 Depends(get_current_user)"
        )
