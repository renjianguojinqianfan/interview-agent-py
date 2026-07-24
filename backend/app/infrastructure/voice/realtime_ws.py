"""DashScope Realtime WebSocket 出站连接原语：供 ASR(#15)/TTS(#16) 客户端共用。

ASR 与 TTS 连接同一 realtime 端点，send/recv/close 契约一致；连接 Protocol、connector
类型、默认 websockets 连接实现、事件 ID 与连接 URI 构造在此共享，避免重复。
connector 可注入以便测试。
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol, cast


class RealtimeConnection(Protocol):
    """出站 realtime WebSocket 连接的最小契约（便于注入与测试）。"""

    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


RealtimeConnector = Callable[[str, dict[str, str]], Awaitable[RealtimeConnection]]


def new_event_id() -> str:
    """生成单次连接内唯一的客户端事件 ID。"""
    return f"event_{uuid.uuid4().hex}"


def build_realtime_uri(url: str, model: str) -> str:
    """构造带 model 查询参数的连接 URI。"""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}model={model}"


async def default_connect(uri: str, headers: dict[str, str]) -> RealtimeConnection:
    import websockets

    conn = await websockets.connect(uri, additional_headers=headers)
    return cast(RealtimeConnection, conn)
