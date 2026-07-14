# 配置管理拆分静态/动态，去掉 YAML 中间层

Java LLM Provider 配置有三级来源：数据库 > YAML 文件（`~/.interview-guide/llm-providers.yml`）> 默认值，且支持运行时 `reload()` 热更新。pydantic-settings 是启动时只读的，无法处理运行时可写。我们决定拆分两类配置：静态配置（DB/Redis/S3 连接、CORS、语音参数等）用 pydantic-settings 读 `.env`；动态配置（LLM Provider 列表）用数据库 + 内存缓存，去掉 YAML 文件中间层。首次启动时检测若无 Provider 则创建默认 dashscope 记录（API Key 空，用户在 UI 填写）。

**Considered Options**: 保留 YAML 中间层 / 去掉（选定）。YAML 中间层是 Spring 配置体系的产物，Python 不需要；数据库已覆盖运行时可读写需求。
