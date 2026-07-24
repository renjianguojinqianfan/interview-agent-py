"""语音面试 WebSocket 路由：实时 ASR 转写（#15，阶段 7B 第一段）。

端点 /ws/voice-interview/{session_id}，握手校验与 ASR 桥接由 VoiceWsOrchestrator 编排。
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, WebSocket

from app.api.deps import get_voice_ws_orchestrator_factory
from app.application.voice.ws_handler import VoiceWsOrchestrator

router = APIRouter(tags=["语音面试WebSocket"])


@router.websocket("/ws/voice-interview/{session_id}")
async def voice_interview_ws(
    websocket: WebSocket,
    session_id: int,
    orchestrator_factory: Callable[[int], VoiceWsOrchestrator] = Depends(get_voice_ws_orchestrator_factory),
) -> None:
    orchestrator = orchestrator_factory(session_id)
    await orchestrator.run(websocket)
