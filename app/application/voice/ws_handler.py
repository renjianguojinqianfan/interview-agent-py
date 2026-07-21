"""语音面试 WebSocket 编排：握手校验 + 全双工桥接（ASR 转写 / LLM 流式 / 句子级并发 TTS）。

流程（#15 + #16）：
1. 握手校验：cache→DB，仅 IN_PROGRESS 放行（4004 不存在 / 4003 状态非法）。
2. 建立 ASR 出站连接；加载 TTS 配置与对话上下文。
3. 双向泵：
   - 客户端 -> ASR：audio（回声抑制窗口内丢弃）转发 send_audio；control(finish/stop) 结束。
   - ASR -> 客户端：partial -> subtitle(isFinal=false)；final -> 累积 mergeBuffer，达 20 字或
     静音 debounce(2500ms) 触发一次「回合」。
4. 回合（_commit_turn）：合并用户回答 -> LLM 流式（text final=false 逐 token，final=true 收尾）
   -> 句子检测 -> 句子级并发 TTS（Semaphore(3) + wait_for(8s)）-> audio_chunk（base64 PCM 分块，
   末尾 isLast 标记）。AI 说话期间 + 结束后 800ms 冷却丢弃麦克风输入（回声抑制）。

不含（#17）：阶段切换、开场问题、暂停超时警告、ASR 重连、对话消息 DB 持久化（仅内存历史）。
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from typing import Protocol

from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.voice.dialogue_llm import DialogueContext, VoiceDialogueLlm
from app.application.voice.ws_schemas import (
    AudioChunkMessage,
    AudioMessage,
    ControlMessage,
    ErrorMessage,
    SubtitleMessage,
    TextMessage,
    parse_client_message,
)
from app.domain.entities.voice_interview import VoiceSessionStatus
from app.domain.services.voice_dialogue import (
    ECHO_COOLDOWN_MS,
    TTS_MAX_CONCURRENCY,
    TTS_TIMEOUT_SECONDS,
    merge_segments,
    should_commit,
    should_drop_audio,
    split_sentences,
)
from app.infrastructure.db.models.voice_interview import VoiceInterviewSession as VoiceInterviewSessionORM
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository
from app.infrastructure.redis.voice_session_cache import VoiceInterviewSessionCache
from app.infrastructure.voice.asr import AsrConnectionClosed, AsrConnectionConfig, AsrError, AsrTranscript
from app.infrastructure.voice.config import AsrConfigLoader, TtsConfigLoader
from app.infrastructure.voice.tts import TtsConnectionClosed, TtsConnectionConfig, TtsError, TtsEvent

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


class TtsClient(Protocol):
    """TTS 客户端最小契约（QwenTtsClient 结构满足）。"""

    async def connect(self) -> None: ...

    async def synthesize(self, text: str) -> None: ...

    async def finish(self) -> None: ...

    async def close(self) -> None: ...

    async def receive(self) -> TtsEvent | None: ...


def _now_ms() -> float:
    return time.monotonic() * 1000


def _parse_provider_id(llm_provider: str | None) -> int | None:
    if not llm_provider:
        return None
    try:
        return int(llm_provider)
    except ValueError:
        return None


def _build_context(orm: VoiceInterviewSessionORM) -> DialogueContext:
    return DialogueContext(
        role_type=orm.role_type,
        skill_id=orm.skill_id,
        difficulty=orm.difficulty,
        current_phase=orm.current_phase,
        custom_jd_text=orm.custom_jd_text,
        llm_provider_id=_parse_provider_id(orm.llm_provider),
    )


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
        tts_config_loader: TtsConfigLoader,
        tts_client_factory: Callable[[TtsConnectionConfig], TtsClient],
        dialogue_llm: VoiceDialogueLlm,
        now_ms: Callable[[], float] | None = None,
        debounce_ms: float = 2500,
    ) -> None:
        self._session_id = session_id
        self._cache = cache
        self._repository = repository
        self._session_factory = session_factory
        self._asr_config_loader = asr_config_loader
        self._asr_client_factory = asr_client_factory
        self._tts_config_loader = tts_config_loader
        self._tts_client_factory = tts_client_factory
        self._dialogue_llm = dialogue_llm
        self._now = now_ms or _now_ms
        self._debounce_ms = debounce_ms

        self._final_segments: list[str] = []
        self._history: list[tuple[str, str]] = []
        self._context: DialogueContext | None = None
        self._tts_config: TtsConnectionConfig | None = None
        self._mute_until_ms: float = 0.0
        self._ai_speaking: bool = False
        self._audio_index: int = 0
        self._turn_lock = asyncio.Lock()
        self._commit_task: asyncio.Task[None] | None = None

    @property
    def history(self) -> list[tuple[str, str]]:
        """内存对话历史（(用户回答, AI 回复) 对），供下游/测试读取。"""
        return list(self._history)

    async def run(self, ws: ClientWebSocket) -> None:
        status = await self._load_session_status()
        if status is None:
            await ws.close(WS_CLOSE_SESSION_NOT_FOUND)
            return
        if status != VoiceSessionStatus.IN_PROGRESS.value:
            await ws.close(WS_CLOSE_INVALID_STATE)
            return

        await ws.accept()
        orm = await self._load_session_orm()
        if orm is None:
            await self._safe_send(ws, ErrorMessage(code="session_gone", message="会话已删除"))
            return
        self._context = _build_context(orm)
        self._tts_config = await self._tts_config_loader.load()

        asr = self._asr_client_factory(await self._asr_config_loader.load())
        try:
            await asr.connect()
            await self._pump(ws, asr)
        finally:
            await self._cancel_commit_task()
            await asr.close()

    async def _load_session_status(self) -> str | None:
        try:
            cached = await self._cache.get_session(self._session_id)
        except Exception as e:
            logger.warning("语音会话缓存读取失败，回退数据库: sessionId=%s, error=%s", self._session_id, e)
            cached = None
        if cached is not None:
            return cached.status
        orm = await self._load_session_orm()
        return orm.status if orm is not None else None

    async def _load_session_orm(self) -> VoiceInterviewSessionORM | None:
        async with self._session_factory() as session:
            return await self._repository.get_by_id(session, self._session_id)

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
                if self._should_drop_incoming():
                    continue  # 回声抑制：AI 说话中 / 冷却期内丢弃麦克风输入
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
                await self._on_final_transcript(ws, transcript.text)
            else:
                await self._safe_send(ws, SubtitleMessage(text=transcript.text, is_final=False))

    async def _on_final_transcript(self, ws: ClientWebSocket, text: str) -> None:
        self._final_segments.append(text)
        merged = merge_segments(self._final_segments)
        if should_commit(merged, silence_ms=0):
            # 达长度阈值：立即提交，取消未决防抖
            await self._cancel_commit_task()
            await self._commit_turn(ws)
        else:
            # 未达阈值：重置静音防抖计时，静音超时后提交
            self._schedule_debounce(ws)

    def _schedule_debounce(self, ws: ClientWebSocket) -> None:
        if self._commit_task is not None and not self._commit_task.done():
            self._commit_task.cancel()
        self._commit_task = asyncio.create_task(self._debounce_then_commit(ws))

    async def _debounce_then_commit(self, ws: ClientWebSocket) -> None:
        try:
            await asyncio.sleep(self._debounce_ms / 1000)
        except asyncio.CancelledError:
            return
        await self._commit_turn(ws)

    async def _cancel_commit_task(self) -> None:
        if self._commit_task is not None and not self._commit_task.done():
            self._commit_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._commit_task
        self._commit_task = None

    async def _commit_turn(self, ws: ClientWebSocket) -> None:
        async with self._turn_lock:
            answer = merge_segments(self._final_segments)
            self._final_segments.clear()
            if not answer or self._context is None:
                return

            # 半双工：本回合内联跑完 LLM 流式 + TTS，期间 _ai_speaking 使回声抑制丢弃麦克风输入。
            self._ai_speaking = True
            try:
                reply_parts: list[str] = []
                pending = ""
                semaphore = asyncio.Semaphore(TTS_MAX_CONCURRENCY)
                sentence_tasks: list[asyncio.Task[list[str]]] = []
                try:
                    async for token in self._dialogue_llm.stream_reply(self._context, self._format_history(), answer):
                        reply_parts.append(token)
                        await self._safe_send(ws, TextMessage(text=token, is_final=False))
                        pending += token
                        sentences, pending = split_sentences(pending)
                        for sentence in sentences:
                            sentence_tasks.append(asyncio.create_task(self._synthesize_sentence(sentence, semaphore)))
                    remainder = pending.strip()
                    if remainder:
                        sentence_tasks.append(asyncio.create_task(self._synthesize_sentence(remainder, semaphore)))
                except Exception as e:
                    logger.warning("语音 LLM 流式回复失败: sessionId=%s, error=%s", self._session_id, e)
                    await self._safe_send(ws, ErrorMessage(code="llm_error", message="生成回复失败"))

                reply = "".join(reply_parts).strip()
                await self._safe_send(ws, TextMessage(text=reply, is_final=True))
                # 句子级并发合成，但按句子顺序发送音频块，保证前端播放顺序正确。
                await self._emit_audio_in_order(ws, sentence_tasks)
                await self._safe_send(ws, AudioChunkMessage(index=self._next_audio_index(), data="", is_last=True))
                if reply:
                    self._history.append((answer, reply))
            finally:
                self._ai_speaking = False
                self._mute_until_ms = self._now() + ECHO_COOLDOWN_MS

    async def _emit_audio_in_order(self, ws: ClientWebSocket, tasks: list[asyncio.Task[list[str]]]) -> None:
        """按句子创建顺序等待各合成任务并发送音频块，逐任务隔离异常（不静默吞没）。"""
        for task in tasks:
            try:
                chunks = await task
            except TimeoutError:
                logger.warning("TTS 合成超时: sessionId=%s", self._session_id)
                continue
            except TtsError as e:
                await self._safe_send(ws, ErrorMessage(code=e.code, message=e.message))
                continue
            except Exception as e:
                logger.warning("TTS 合成任务异常: sessionId=%s, error=%s", self._session_id, e)
                continue
            for chunk in chunks:
                await self._safe_send(ws, AudioChunkMessage(index=self._next_audio_index(), data=chunk, is_last=False))

    async def _synthesize_sentence(self, sentence: str, semaphore: asyncio.Semaphore) -> list[str]:
        """合成单句，返回 base64 PCM 音频块列表（发送由 _emit_audio_in_order 按序执行）。"""
        if self._tts_config is None:
            return []
        async with semaphore:
            tts = self._tts_client_factory(self._tts_config)
            try:
                return await asyncio.wait_for(self._run_tts(tts, sentence), timeout=TTS_TIMEOUT_SECONDS)
            finally:
                await tts.close()

    async def _run_tts(self, tts: TtsClient, sentence: str) -> list[str]:
        chunks: list[str] = []
        await tts.connect()
        await tts.synthesize(sentence)
        while True:
            try:
                event = await tts.receive()
            except TtsConnectionClosed:
                break
            if event is None:
                continue
            if event.done:
                break
            if event.audio_base64:
                chunks.append(event.audio_base64)
        return chunks

    def _next_audio_index(self) -> int:
        index = self._audio_index
        self._audio_index += 1
        return index

    def _should_drop_incoming(self) -> bool:
        return self._ai_speaking or should_drop_audio(self._now(), self._mute_until_ms)

    def _format_history(self) -> str:
        lines: list[str] = []
        for user_answer, ai_reply in self._history:
            lines.append(f"候选人：{user_answer}")
            lines.append(f"面试官：{ai_reply}")
        return "\n".join(lines)

    async def _safe_send(
        self,
        ws: ClientWebSocket,
        message: SubtitleMessage | TextMessage | AudioChunkMessage | ErrorMessage,
    ) -> None:
        try:
            await ws.send_text(json.dumps(message.model_dump(by_alias=True), ensure_ascii=False))
        except Exception as e:
            logger.warning("向客户端发送消息失败: sessionId=%s, error=%s", self._session_id, e)
