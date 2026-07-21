# ASR/TTS 运行时配置存数据库（扩展 ADR-0004）

ADR-0004 将配置拆分为静态（pydantic-settings 读 .env）和动态（数据库 + 内存缓存），其中"语音参数"被列为静态配置。但 Java 原始设计中 ASR/TTS 的完整运行时配置（url、model、apiKey、language、sample_rate 等 19 个字段）存储在 YAML 文件中，支持运行时通过 API 修改并 reload。ADR-0004 去掉了 YAML 中间层，这些运行时可写的 ASR/TTS 配置需要新的持久化方案。

**决策**：新建 `voice_config` 单例表（id=1）存储 ASR/TTS 全量参数，API Key 加密存储（AES-GCM，复用 ApiKeyEncryptionService）。通过 `/api/llm-provider/voice/asr` 和 `/api/llm-provider/voice/tts` 接口读写。ADR-0004 中提到的"语音参数"（settings.py 中的 voice_asr_language、voice_tts_voice 等）仍为静态配置，仅用于基础默认值；运行时可修改的完整 ASR/TTS 配置走数据库。ASR 与 TTS 的 api_key 独立存储（`asr_api_key` / `tts_api_key` 两列），`update_asr_config` 与 `update_tts_config` 各只写自身 key（R5 review 修正：原实现双向同步两 key，已解除耦合）。连通性测试：`POST /voice/asr/test` + `POST /voice/tts/test`，均 TCP 连接 `asr_url` 主机（dashscope ASR/TTS 共用 realtime 网关）。

**Considered Options**: 扩展 LlmGlobalSetting 加 JSON 列 / 独立 voice_config 表（选定）。独立表职责分离更清晰，stage 7 语音模块可直接复用，且避免 LlmGlobalSetting 同时管理 LLM 默认供应商和语音配置导致 Divergent Change。
