"""语音音频工具：PCM -> WAV 转换（纯字节处理，零框架依赖）。

Qwen TTS 输出为裸 PCM（24kHz/16-bit/mono）；前端 audio_chunk 契约要求每块自带标准 44 字节
WAV 头（handleAudioChunk 跳过前 44 字节取 PCM）。对应 migration-plan 7B.3 与 Java
sendAudioChunk(convertPcmToWav(pcm), ...)。
"""

import base64
import struct

_PCM_FORMAT = 1  # WAV 格式码：PCM
_WAV_HEADER_SIZE = 44

TTS_OUTPUT_SAMPLE_RATE = 24000
"""Qwen TTS Realtime 输出裸 PCM 采样率（24kHz，附录 F；前端 AudioContext 亦为 24000）。"""


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


def pcm_base64_to_wav_base64(pcm_base64: str, sample_rate: int = TTS_OUTPUT_SAMPLE_RATE) -> str:
    """裸 PCM 的 base64 -> 带 44 字节 WAV 头的 base64（前端 audio_chunk 每块自带 WAV 头）。"""
    pcm = base64.b64decode(pcm_base64)
    return base64.b64encode(pcm_to_wav(pcm, sample_rate)).decode("ascii")
