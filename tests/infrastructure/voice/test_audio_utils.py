"""PCM -> WAV 音频工具测试。"""

import base64
import struct

from app.infrastructure.voice.audio_utils import (
    TTS_OUTPUT_SAMPLE_RATE,
    build_wav_header,
    pcm_base64_to_wav_base64,
    pcm_to_wav,
)


class TestBuildWavHeader:
    def test_header_is_44_bytes(self) -> None:
        header = build_wav_header(pcm_len=1000, sample_rate=24000)
        assert len(header) == 44

    def test_riff_wave_fmt_data_markers(self) -> None:
        header = build_wav_header(pcm_len=0, sample_rate=24000)
        assert header[0:4] == b"RIFF"
        assert header[8:12] == b"WAVE"
        assert header[12:16] == b"fmt "
        assert header[36:40] == b"data"

    def test_sample_rate_and_sizes_encoded(self) -> None:
        header = build_wav_header(pcm_len=100, sample_rate=24000)
        assert struct.unpack("<I", header[4:8])[0] == 36 + 100  # RIFF chunk size
        assert struct.unpack("<H", header[20:22])[0] == 1  # PCM format
        assert struct.unpack("<H", header[22:24])[0] == 1  # mono
        assert struct.unpack("<I", header[24:28])[0] == 24000  # sample rate
        assert struct.unpack("<H", header[34:36])[0] == 16  # bits per sample
        assert struct.unpack("<I", header[40:44])[0] == 100  # data size


class TestPcmToWav:
    def test_prepends_header(self) -> None:
        pcm = b"\x01\x02\x03\x04"
        wav = pcm_to_wav(pcm, sample_rate=24000)
        assert len(wav) == 44 + len(pcm)
        assert wav[:4] == b"RIFF"
        assert wav[44:] == pcm


class TestPcmBase64ToWavBase64:
    def test_wraps_pcm_base64_into_wav_base64(self) -> None:
        pcm = b"ABC"
        wav = base64.b64decode(pcm_base64_to_wav_base64(base64.b64encode(pcm).decode()))
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert len(wav) == 44 + len(pcm)
        assert wav[44:] == pcm  # 前端跳过前 44 字节即可取回原始 PCM

    def test_default_sample_rate_is_24000(self) -> None:
        wav = base64.b64decode(pcm_base64_to_wav_base64(base64.b64encode(b"\x00\x00").decode()))
        assert struct.unpack("<I", wav[24:28])[0] == TTS_OUTPUT_SAMPLE_RATE
