"""语音音频工具：PCM -> WAV 转换（纯字节处理，零框架依赖）。

Qwen TTS 输出为裸 PCM（默认 24kHz/16-bit/mono）；合并模式或前端重建需要标准 44 字节
WAV 头。对应 migration-plan 7B.3（PCM->WAV 44 字节头 24kHz/16-bit/mono）。
"""

import struct

_PCM_FORMAT = 1  # WAV 格式码：PCM
_WAV_HEADER_SIZE = 44


def build_wav_header(
    pcm_len: int,
    sample_rate: int,
    channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """构造 44 字节 WAV 头（RIFF/WAVE/fmt /data，小端）。"""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", _WAV_HEADER_SIZE - 8 + pcm_len),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),
            struct.pack("<H", _PCM_FORMAT),
            struct.pack("<H", channels),
            struct.pack("<I", sample_rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", bits_per_sample),
            b"data",
            struct.pack("<I", pcm_len),
        ]
    )


def pcm_to_wav(
    pcm: bytes,
    sample_rate: int,
    channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """在裸 PCM 前拼接 44 字节 WAV 头。"""
    return build_wav_header(len(pcm), sample_rate, channels, bits_per_sample) + pcm
