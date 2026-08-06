"""上传请求大小双段校验（ST-02/SEC-05）。

- 读前预检：按 Content-Length 头拦截超限请求，避免先全量读入内存（内存 DoS）。
- 读后兜底：头缺失/伪造时按实际字节数校验。
"""

from fastapi import HTTPException, Request


def check_upload_size(request: Request, max_bytes: int, data: bytes | None = None) -> None:
    """上传大小校验：Content-Length 超限立即抛 413；data 传入时再按实际长度兜底。

    头缺失/非法时跳过预检，交由读后兜底。
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except ValueError:
            length = -1
        if length > max_bytes:
            _raise_too_large(max_bytes)
    if data is not None and len(data) > max_bytes:
        _raise_too_large(max_bytes)


def _raise_too_large(max_bytes: int) -> None:
    max_mb = max_bytes // (1024 * 1024)
    raise HTTPException(status_code=413, detail=f"文件大小超过限制（最大 {max_mb}MB）")
