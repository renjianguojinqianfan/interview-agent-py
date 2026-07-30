"""语音面试 WebSocket 路由：实时 ASR 转写（#15，阶段 7B 第一段）。

端点 /ws/voice-interview/{session_id}，握手校验与 ASR 桥接由 VoiceWsOrchestrator 编排。
"""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, WebSocket

from app.api.deps import get_voice_ws_orchestrator_factory
from app.application.voice.ws_handler import VoiceWsOrchestrator
from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["语音面试WebSocket"])

# NOTE: 进程级计数器，多 Worker 部署需替换为 Redis 原子计数
_active_connection_count: int = 0


@router.websocket("/ws/voice-interview/{session_id}")
async def voice_interview_ws(
    websocket: WebSocket,
    session_id: int,
    orchestrator_factory: Callable[[int], VoiceWsOrchestrator] = Depends(get_voice_ws_orchestrator_factory),
) -> None:
    global _active_connection_count  # noqa: PLW0603
    if _active_connection_count >= settings.voice_max_ws_connections:
        await websocket.close(code=4005, reason="服务器连接数已满")
        logger.warning(
            "WS 连接被拒绝，已达上限 %d: sessionId=%s",
            settings.voice_max_ws_connections,
            session_id,
        )
        return

    _active_connection_count += 1
    try:
        orchestrator = orchestrator_factory(session_id)
        await orchestrator.run(websocket)
    finally:
        _active_connection_count -= 1
