"""语音面试 WebSocket 编排：握手校验 + ASR 桥接（客户端音频 <-> ASR 转写）。

流程（#15 范围）：
1. 握手校验：按 session_id 查缓存（未命中回退 DB），仅 IN_PROGRESS 放行，否则以
   应用级关闭码拒绝（4004 会话不存在 / 4003 状态非法）。
2. 建立 Qwen ASR 出站连接。
3. 双向泵（asyncio 并发）：
   - 客户端 -> ASR：audio 转发 send_audio；control(finish/stop) 触发 asr.finish 并结束。
   - ASR -> 客户端：partial -> subtitle(isFinal=false)；final -> 累积 mergeBuffer
     （不回推字幕，与 #15 AC 一致）；error -> error 消息。
4. 清理：关闭 ASR 连接。

不含：TTS、语音 LLM、回声抑制、句子级并发、阶段切换、开场问题、重连（#16/#17）。
mergeBuffer 的下游提交（should_commit -> LLM）由 #16/#17 接入；本 issue 仅累积 final 片段。
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Protocol

from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.voice.ws_schemas import (
    AudioMessage,
    ControlMessage,
    ErrorMessage,
    SubtitleMessage,
    parse_client_message,
)
from app.domain.entities.voice_interview import VoiceSessionStatus
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository
from app.infrastructure.redis.voice_session_cache import VoiceInterviewSessionCache
from app.infrastructure.voice.asr import (
    AsrConnectionClosed,
    AsrConnectionConfig,
    AsrError,
    AsrTranscript,
)
from app.infrastructure.voice.config import AsrConfigLoader

logger = logging.getLogger(__name__)

WS_CLOSE_SESSION_NOT_FOUND = 4004
WS_CLOSE_INVALID_STATE = 4003

_CONTROL_FINISH_ACTIONS = frozenset({"finish", "stop"})


class ClientWebSocket(Protocol):
    """面向客户端的服务端 WebSocket 最小契约（FastAPI WebSocket 结构满足）。"""

    async def accept(self) -> None: ...

    async def receive_text(self) -> str: ...

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


class AsrClient(Protocol):
    """ASR 客户端最小契约（QwenAsrClient 结构满足）。"""

    async def connect(self) -> None: ...

    async def send_audio(self, base64_pcm: str) -> None: ...

    async def finish(self) -> None: ...

    async def close(self) -> None: ...

    async def receive(self) -> AsrTranscript | None: ...


class VoiceWsOrchestrator:
    """单个语音面试 WebSocket 连接的编排器（每次连接实例化一次）。"""

    def __init__(
        self,
        session_id: int,
        cache: VoiceInterviewSessionCache,
        repository: VoiceInterviewRepository,
        session_factory: async_sessionmaker[AsyncSession],
        asr_config_loader: AsrConfigLoader,
        asr_client_factory: Callable[[AsrConnectionConfig], AsrClient],
    ) -> None:
        self._session_id = session_id
        self._cache = cache
        self._repository = repository
        self._session_factory = session_factory
        self._asr_config_loader = asr_config_loader
        self._asr_client_factory = asr_client_factory
        self._final_segments: list[str] = []

    @property
    def final_segments(self) -> list[str]:
        """已累积的 final 转写片段（mergeBuffer 内容），供下游/测试读取。"""
        return list(self._final_segments)

    async def run(self, ws: ClientWebSocket) -> None:
        status = await self._load_session_status()
        if status is None:
            await ws.close(WS_CLOSE_SESSION_NOT_FOUND)
            return
        if status != VoiceSessionStatus.IN_PROGRESS.value:
            await ws.close(WS_CLOSE_INVALID_STATE)
            return

        await ws.accept()
        config = await self._asr_config_loader.load()
        asr = self._asr_client_factory(config)
        try:
            await asr.connect()
            await self._pump(ws, asr)
        finally:
            await asr.close()

    async def _load_session_status(self) -> str | None:
        try:
            cached = await self._cache.get_session(self._session_id)
        except Exception as e:
            logger.warning("语音会话缓存读取失败，回退数据库: sessionId=%s, error=%s", self._session_id, e)
            cached = None
        if cached is not None:
            return cached.status
        async with self._session_factory() as session:
            orm = await self._repository.get_by_id(session, self._session_id)
            return orm.status if orm is not None else None

    async def _pump(self, ws: ClientWebSocket, asr: AsrClient) -> None:
        client_task = asyncio.create_task(self._client_to_asr(ws, asr))
        asr_task = asyncio.create_task(self._asr_to_client(ws, asr))
        done, pending = await asyncio.wait({client_task, asr_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None:
                logger.warning("语音 WS 泵任务异常，连接终止: sessionId=%s, error=%s", self._session_id, exc)

    async def _client_to_asr(self, ws: ClientWebSocket, asr: AsrClient) -> None:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            try:
                message = parse_client_message(json.loads(raw))
            except (ValueError, json.JSONDecodeError):
                await self._safe_send(ws, ErrorMessage(code="bad_message", message="消息解析失败"))
                continue
            if isinstance(message, AudioMessage):
                await asr.send_audio(message.data)
            elif isinstance(message, ControlMessage) and message.action in _CONTROL_FINISH_ACTIONS:
                await asr.finish()
                break

    async def _asr_to_client(self, ws: ClientWebSocket, asr: AsrClient) -> None:
        while True:
            try:
                transcript = await asr.receive()
            except AsrConnectionClosed:
                break
            except AsrError as e:
                await self._safe_send(ws, ErrorMessage(code=e.code, message=e.message))
                continue
            if transcript is None:
                continue
            if transcript.is_final:
                # #15 AC：final 仅累积到 mergeBuffer，不回推字幕（下游提交由 #16/#17 接入）
                self._final_segments.append(transcript.text)
            else:
                await self._safe_send(ws, SubtitleMessage(text=transcript.text, is_final=False))

    async def _safe_send(self, ws: ClientWebSocket, message: SubtitleMessage | ErrorMessage) -> None:
        try:
            await ws.send_text(json.dumps(message.model_dump(by_alias=True), ensure_ascii=False))
        except Exception as e:
            logger.warning("向客户端发送消息失败: sessionId=%s, error=%s", self._session_id, e)
