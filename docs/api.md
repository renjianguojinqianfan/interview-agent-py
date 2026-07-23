# interview-agent-py API 接口文档

> 本文档依据 **Python 后端实际实现的路由**（`app/api/routers/`）整理，供前端联调与接口使用者参考。
> 字段一律以对外的 **camelCase** 形式列出（后端 `BaseSchema` 由 snake_case 经 `to_camel` 自动转换）。
> 文档末尾「附录 B：已知契约差异」列出与复用的 Java 前端契约尚未对齐的缺口（终局迁移审查结论）。

## 目录

- [1. 通用约定](#1-通用约定)
- [2. 错误码](#2-错误码)
- [3. 系统](#3-系统)
- [4. 简历管理 `/api/resumes`](#4-简历管理-apiresumes)
- [5. 技能管理 `/api/interview/skills`](#5-技能管理-apiinterviewskills)
- [6. 文字面试 `/api/interview`](#6-文字面试-apiinterview)
- [7. 面试日程 `/api/interview-schedule`](#7-面试日程-apiinterview-schedule)
- [8. 知识库 `/api/knowledgebase`](#8-知识库-apiknowledgebase)
- [9. RAG 问答 `/api/rag-chat/sessions`](#9-rag-问答-apirag-chatsessions)
- [10. LLM 供应商 `/api/llm-provider`](#10-llm-供应商-apillm-provider)
- [11. 语音面试 `/api/voice-interview`](#11-语音面试-apivoice-interview)
- [12. WebSocket 语音链路 `/ws/voice-interview/{sessionId}`](#12-websocket-语音链路-wsvoice-interviewsessionid)
- [附录 A：核心数据结构](#附录-a核心数据结构)
- [附录 B：已知契约差异（待修复）](#附录-b已知契约差异待修复)

---

## 1. 通用约定

### 1.1 Base URL

| 环境 | Base URL | 说明 |
|---|---|---|
| 本地后端 | `http://localhost:8000` | `uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| 前端开发 | `http://localhost:5173` | Vite 代理 `/api`、`/ws` 到 `8000` |

所有业务接口均以 `/api` 为前缀；WebSocket 以 `/ws` 为前缀。

### 1.2 统一响应结构（ADR-0003）

**所有 JSON 接口一律返回 HTTP `200`**，业务结果包裹在 `Result` 中：

```jsonc
{
  "code": 200,        // 200=成功；非 200=业务错误码（见第 2 节）
  "message": "success",
  "data": { }          // 成功时为业务数据；失败时为 null
}
```

- 成功：`code === 200`，取 `data`。
- 失败：`code !== 200`，`message` 为可直接展示的错误文案，`data` 为 `null`。
- 前端拦截器约定：`code===200` 返回 `data`，否则 reject(`message`)。

> 例外：**文件下载 / PDF 导出**直接返回二进制流（`Content-Disposition: attachment`）；**SSE 流式**返回 `text/event-stream`。二者不包裹 `Result`（出错时才以 `Result` JSON/`event: error` 帧返回）。

### 1.3 字段与时间

- 请求体与响应体字段统一 **camelCase**。
- `datetime` 字段对外为**无时区偏移的 ISO 8601 裸串**（如 `2026-07-23T10:30:00`），内部按 UTC aware 存储（ADR-0013）。

### 1.4 认证与限流

- **无认证**（ADR-0007）。限流可选注入 `X-User-Id` 头启用 USER 维度，否则仅 GLOBAL + IP。
- 部分接口带每秒限流（下文各接口「限流」列标注，如 `5/s`）。超限返回 `code=8001`。

### 1.5 通用参数约定

- 路径参数：`{sessionId}`、`{id}` 等，类型见各接口。
- 上传：`multipart/form-data`，文件字段名 `file`。
- 允许上传类型：PDF / Word(doc/docx) / txt / markdown；大小上限 **10 MB**。

---

## 2. 错误码

| code | 含义 | code | 含义 |
|---|---|---|---|
| 200 | 成功 | 6001 | 知识库不存在 |
| 400 | 请求参数错误 | 6002 | 知识库文件解析失败 |
| 401 | 未授权 | 6003 | 知识库上传失败 |
| 403 | 禁止访问 | 6004 | 知识库查询失败 |
| 404 | 资源不存在 | 6005 | 知识库删除失败 |
| 405 | 请求方法不支持 | 6006 | 知识库向量化失败 |
| 500 | 服务器内部错误 | 6007 | RAG 会话不存在 |
| 2001 | 简历不存在 | 7001 | AI 服务暂时不可用 |
| 2002 | 简历解析失败 | 7002 | AI 服务响应超时 |
| 2003 | 简历上传失败 | 7003 | AI 服务调用失败 |
| 2004 | 简历已存在 | 7004 | AI 服务密钥无效 |
| 2006 | 不支持的文件类型 | 7005 | AI 服务调用频率超限 |
| 2007 | 简历分析失败 | 8001 | 请求过于频繁，请稍后再试 |
| 2008 | 简历分析结果不存在 | 9001 | 面试日程不存在 |
| 3001 | 面试会话不存在 | 10001 | 语音面试会话不存在 |
| 3002 | 面试会话已过期 | 10004 | 语音面试评估失败 |
| 3003 | 面试问题不存在 | 11001 | LLM Provider 不存在 |
| 3004 | 面试已完成 | 11002 | LLM Provider 已存在 |
| 3005 | 面试评估失败 | 11004 | 读取 Provider 配置失败 |
| 3006 | 面试问题生成失败 | 11005 | 写入 Provider 配置失败 |
| 3007 | 面试尚未完成 | 11006 | Provider 连通性测试失败 |
| 3008 | 面试答案保存失败 | 11007 | 默认 Provider 不可删除 |
| 3009 | 技能不存在 | 11008 | 模块不存在 |
| 3010 | JD 解析失败 | 11009 | 读取语音服务配置失败 |
| 3011 | 面试评估结果不存在 | 11010 | 写入语音服务配置失败 |
| 4001~4003 | 文件上传/下载/删除失败 | 11011 | 语音服务连通性测试失败 |
| 5001 | PDF 导出失败 | | |

---

## 3. 系统

| 方法 | 路径 | 说明 | 响应 `data` |
|---|---|---|---|
| GET | `/health` | 健康检查 | `{ "status": "healthy" }` |

---

## 4. 简历管理 `/api/resumes`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| POST | `/api/resumes/upload` | 上传简历（异步分析） | `multipart: file` | [`ResumeUploadResponse`](#resumeuploadresponse) | 5/s |
| GET | `/api/resumes` | 简历列表（**裸数组**） | - | [`ResumeListItem`](#resumelistitem)`[]` | - |
| GET | `/api/resumes/statistics` | 简历统计 | - | `{ totalCount, totalInterviewCount, totalAccessCount }` | - |
| GET | `/api/resumes/{resumeId}/detail` | 简历详情（含分析、关联面试） | - | [`ResumeDetail`](#resumedetail) | - |
| DELETE | `/api/resumes/{resumeId}` | 删除简历 | - | `null` | - |
| POST | `/api/resumes/{resumeId}/reanalyze` | 重新分析 | - | `null` | 2/s |
| GET | `/api/resumes/{resumeId}/export` | 导出分析报告 PDF | - | *PDF 二进制* | - |

- 分析为异步：上传后 `analyzeStatus=PENDING`，通过详情轮询 `analyzeStatus`（`PENDING/PROCESSING/COMPLETED/FAILED`）。

---

## 5. 技能管理 `/api/interview/skills`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| GET | `/api/interview/skills` | 技能列表 | - | [`SkillDTO`](#skilldto)`[]` | - |
| GET | `/api/interview/skills/{skillId}` | 技能详情 | - | [`SkillDTO`](#skilldto) | - |
| POST | `/api/interview/skills/parse-jd` | 解析 JD 为面试分类 | `{ jdText }` | [`CategoryDTO`](#categorydto)`[]` | 5/s |

---

## 6. 文字面试 `/api/interview`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| POST | `/api/interview/sessions` | 创建面试会话（AI 出题） | [`CreateInterviewRequest`](#createinterviewrequest) | [`InterviewSession`](#interviewsession) | 5/s |
| GET | `/api/interview/sessions` | 会话列表（**裸数组**） | - | [`SessionListItem`](#sessionlistitem)`[]` | - |
| GET | `/api/interview/sessions/unfinished/{resumeId}` | 查未完成会话 | - | [`InterviewSession`](#interviewsession) | - |
| GET | `/api/interview/sessions/{sessionId}` | 会话信息 | - | [`InterviewSession`](#interviewsession) | - |
| GET | `/api/interview/sessions/{sessionId}/question` | 当前问题 | - | `{ completed, message?, question? }` | - |
| POST | `/api/interview/sessions/{sessionId}/answers` | 提交答案（进入下一题） | `{ questionIndex, answer }` | [`SubmitAnswerResponse`](#submitanswerresponse) | 10/s |
| PUT | `/api/interview/sessions/{sessionId}/answers` | 暂存答案（不进入下一题） | `{ questionIndex, answer }` | `null` | - |
| POST | `/api/interview/sessions/{sessionId}/complete` | 提前交卷 | - | `null` | - |
| DELETE | `/api/interview/sessions/{sessionId}` | 删除会话 | - | `null` | - |
| GET | `/api/interview/sessions/{sessionId}/evaluation` | 获取评估结果（仅会话 `EVALUATED` 时返回，否则报错 `3011`/`3001`） | - | [`EvaluationResult`](#evaluationresult) | - |
| GET | `/api/interview/sessions/{sessionId}/details` | 面试详情（含逐题 `answers[]`；会话不存在报 `3001`） | - | [`InterviewDetail`](#interviewdetail) | - |
| GET | `/api/interview/sessions/{sessionId}/export` | 导出面试报告 PDF | - | *PDF 二进制* | - |

- 交卷后评估为异步（后台消费者生成）：`GET /evaluation` 在会话状态达到 `EVALUATED` 前返回错误码 `3011`（评估结果不存在），完成后返回 `EvaluationResult`；它是「结果查询」端点，非状态轮询端点。
- ✅ 契约提示：复用的前端**查看文字面试详情调用 `GET /sessions/{id}/details`**（`historyApi.getInterviewDetail`，返回 [`InterviewDetail`](#interviewdetail)，含逐题 `answers[]`）。前端 `getReport`→`GET /sessions/{id}/report` 未实现且无页面调用（死端点）；`GET /evaluation` 后端已实现但前端无页面直接调用。详见[附录 B](#附录-b已知契约差异待修复)。

---

## 7. 面试日程 `/api/interview-schedule`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| POST | `/api/interview-schedule/parse` | 解析日程原文（规则+AI） | `{ rawText, source? }` | [`ParseResponse`](#parseresponse) | 5/s |
| POST | `/api/interview-schedule` | 创建日程 | [`CreateScheduleRequest`](#createschedulerequest) | [`InterviewSchedule`](#interviewschedule) | - |
| GET | `/api/interview-schedule` | 日程列表（**裸数组**） | query: `status?`,`start?`,`end?` | [`InterviewSchedule`](#interviewschedule)`[]` | - |
| GET | `/api/interview-schedule/{id}` | 日程详情 | - | [`InterviewSchedule`](#interviewschedule) | - |
| PUT | `/api/interview-schedule/{id}` | 更新日程 | [`CreateScheduleRequest`](#createschedulerequest) | [`InterviewSchedule`](#interviewschedule) | - |
| DELETE | `/api/interview-schedule/{id}` | 删除日程 | - | `null` | - |
| PATCH | `/api/interview-schedule/{id}/status` | 更新状态 | query: `status` | [`InterviewSchedule`](#interviewschedule) | - |

- `interviewType`：`ONSITE` / `VIDEO` / `PHONE`；`status`：`PENDING` / `COMPLETED` / `CANCELLED` / `RESCHEDULED`。
- `source`：`feishu` / `tencent` / `zoom` / `other`。

---

## 8. 知识库 `/api/knowledgebase`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| POST | `/api/knowledgebase/upload` | 上传知识库文件（异步向量化） | `multipart: file, name?, category?` | [`KnowledgeBaseUploadResponse`](#knowledgebaseuploadresponse) | 3/s |
| GET | `/api/knowledgebase/list` | 知识库列表（**裸数组**） | query: `sortBy?`,`vectorStatus?` | [`KnowledgeBaseItem`](#knowledgebaseitem)`[]` | - |
| GET | `/api/knowledgebase/stats` | 统计 | - | [`KnowledgeBaseStats`](#knowledgebasestats) | - |
| GET | `/api/knowledgebase/categories` | 全部分类（**裸数组**） | - | `string[]` | - |
| GET | `/api/knowledgebase/category/{category}` | 按分类查询（**裸数组**） | - | [`KnowledgeBaseItem`](#knowledgebaseitem)`[]` | - |
| GET | `/api/knowledgebase/search` | 关键词搜索（**裸数组**） | query: `keyword` | [`KnowledgeBaseItem`](#knowledgebaseitem)`[]` | - |
| GET | `/api/knowledgebase/{kbId}/download` | 下载原文件 | - | *文件二进制* | - |
| PUT | `/api/knowledgebase/{kbId}/category` | 更新分类 | `{ category }` | `null` | - |
| DELETE | `/api/knowledgebase/{kbId}` | 删除知识库 | - | `null` | - |
| POST | `/api/knowledgebase/{kbId}/revectorize` | 重新向量化（失败重试） | - | `null` | 2/s |

- `sortBy`：`time` / `size` / `access` / `question`；`vectorStatus`：`PENDING` / `PROCESSING` / `COMPLETED` / `FAILED`。
- 向量化异步：上传后 `vectorStatus=PENDING`，前端轮询列表刷新状态。

> ⚠️ 前端 api 模块还声明 `GET /{id}`、`GET /uncategorized`、`POST /query`、`POST /query/stream`，当前 Python **未实现**（`/query`、`/query/stream` 属已文档化死端点；`/{id}`、`/uncategorized` 无页面调用），详见[附录 B](#附录-b已知契约差异待修复)。

---

## 9. RAG 问答 `/api/rag-chat/sessions`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| POST | `/api/rag-chat/sessions` | 创建会话 | `{ knowledgeBaseIds, title? }` | [`RagSession`](#ragsession) | - |
| GET | `/api/rag-chat/sessions` | 会话列表（**裸数组**） | - | [`RagSessionListItem`](#ragsessionlistitem)`[]` | - |
| GET | `/api/rag-chat/sessions/{sessionId}` | 会话详情（含消息、知识库） | - | [`RagSessionDetail`](#ragsessiondetail) | - |
| PUT | `/api/rag-chat/sessions/{sessionId}/title` | 更新标题 | `{ title }` | `null` | - |
| PUT | `/api/rag-chat/sessions/{sessionId}/pin` | 切换置顶 | - | `null` | - |
| DELETE | `/api/rag-chat/sessions/{sessionId}` | 删除会话 | - | `null` | - |
| POST | `/api/rag-chat/sessions/{sessionId}/messages/stream` | 发送消息（**SSE 流式**） | `{ question }` | *见下* | 5/s |

- `sessionId` 为**数字主键**。消息类型字段名为 `type`（`user` / `assistant`），非 `role`。
- **流式格式**（对齐 Java `ServerSentEvent<String>` 与前端 `parseMode:'event'`）：
  - 正常帧：`data: <文本>\n\n`，其中换行被转义为 `\n`/`\r`（前端拼接后再还原）。
  - 错误帧：`event: error\ndata: <错误消息>\n\n`。
  - 无 `[DONE]` 哨兵，流自然结束即完成。

---

## 10. LLM 供应商 `/api/llm-provider`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| GET | `/api/llm-provider/list` | 供应商列表 | - | [`ProviderItem`](#provideritem)`[]` | 30/s |
| POST | `/api/llm-provider` | 新增供应商 | [`CreateProviderRequest`](#createproviderrequest) | `null` | 5/s |
| GET | `/api/llm-provider/{providerId}` | 供应商详情 | - | [`ProviderItem`](#provideritem) | 30/s |
| PUT | `/api/llm-provider/{providerId}` | 更新供应商 | [`UpdateProviderRequest`](#updateproviderrequest) | `null` | 5/s |
| DELETE | `/api/llm-provider/{providerId}` | 删除供应商 | - | `null` | 5/s |
| POST | `/api/llm-provider/{providerId}/test` | 连通性测试 | - | `{ success, message, model }` | 10/s |
| POST | `/api/llm-provider/reload` | 重载供应商注册表 | - | `null` | 5/s |
| GET | `/api/llm-provider/default-provider` | 获取默认 chat/embedding 供应商 | - | `{ defaultProvider, defaultEmbeddingProvider }` | 30/s |
| PUT | `/api/llm-provider/default-provider` | 设置默认 chat 供应商 | `{ defaultProvider, defaultEmbeddingProvider }` | `null` | 5/s |
| PUT | `/api/llm-provider/default-embedding-provider` | 设置默认 embedding 供应商 | `{ defaultProvider, defaultEmbeddingProvider }` | `null` | 5/s |
| GET | `/api/llm-provider/voice/asr` | 获取 ASR 配置 | - | [`AsrConfig`](#asrconfig) | 30/s |
| PUT | `/api/llm-provider/voice/asr` | 更新 ASR 配置 | `AsrConfigRequest` | `null` | 5/s |
| GET | `/api/llm-provider/voice/tts` | 获取 TTS 配置 | - | [`TtsConfig`](#ttsconfig) | 30/s |
| PUT | `/api/llm-provider/voice/tts` | 更新 TTS 配置 | `TtsConfigRequest` | `null` | 5/s |
| POST | `/api/llm-provider/voice/asr/test` | ASR 连通性测试 | - | `{ success, message, model }` | 10/s |
| POST | `/api/llm-provider/voice/tts/test` | TTS 连通性测试 | - | `{ success, message, model }` | 10/s |

- `providerId` 为**字符串**（= provider 名，ADR-0015）。
- `apiKey` 写入时加密存储（AES-256-GCM），读出时以 `maskedApiKey`（首3***尾3）返回，不回传明文。
- `POST /voice/tts/test` 后端已实现，前端 api 模块暂未封装调用。

---

## 11. 语音面试 `/api/voice-interview`

| 方法 | 路径 | 说明 | 请求 | 响应 `data` | 限流 |
|---|---|---|---|---|---|
| POST | `/api/voice-interview/sessions` | 创建语音会话 | [`CreateVoiceSessionRequest`](#createvoicesessionrequest) | [`VoiceSession`](#voicesession)（含 `webSocketUrl`） | 5/s |
| GET | `/api/voice-interview/sessions` | 会话列表（**裸数组**） | query: `userId?`,`status?` | [`VoiceSessionMeta`](#voicesessionmeta)`[]` | - |
| GET | `/api/voice-interview/sessions/{sessionId}` | 会话详情（含 `webSocketUrl`） | - | [`VoiceSession`](#voicesession) | - |
| POST | `/api/voice-interview/sessions/{sessionId}/end` | 结束会话（触发异步评估） | - | `null` | - |
| PUT | `/api/voice-interview/sessions/{sessionId}/pause` | 暂停会话 | `{ reason? }` | `null` | - |
| PUT | `/api/voice-interview/sessions/{sessionId}/resume` | 恢复会话（含 `webSocketUrl`） | - | [`VoiceSession`](#voicesession) | - |
| DELETE | `/api/voice-interview/sessions/{sessionId}` | 删除会话 | - | `null` | - |
| GET | `/api/voice-interview/sessions/{sessionId}/messages` | 会话消息列表（**裸数组**） | - | [`VoiceMessage`](#voicemessage)`[]` | - |
| GET | `/api/voice-interview/sessions/{sessionId}/evaluation` | 获取评估状态/结果 | - | [`VoiceEvaluationStatus`](#voiceevaluationstatus) | - |
| POST | `/api/voice-interview/sessions/{sessionId}/evaluation` | 触发异步评估 | - | [`VoiceEvaluationStatus`](#voiceevaluationstatus) | - |

- `sessionId` 为**数字主键**。`webSocketUrl` 由后端按请求 scheme/host 拼出：`ws(s)://<host>/ws/voice-interview/{id}`。

---

## 12. WebSocket 语音链路 `/ws/voice-interview/{sessionId}`

- 端点：`GET (Upgrade) /ws/voice-interview/{sessionId}`（`sessionId` 数字）。
- 由 `VoiceWsOrchestrator` 编排握手校验与 ASR/TTS 桥接。

**客户端 → 服务端**（JSON 文本帧）：

| type | 字段 | 说明 |
|---|---|---|
| `audio` | `data`(Base64), `timestamp?` | 上行音频分片 |
| `control` | `action`, `data?`, `timestamp?` | 控制指令 |

**服务端 → 客户端**（JSON 文本帧）：

| type | 字段 | 说明 |
|---|---|---|
| `subtitle` | `text`, `isFinal` | ASR 转写字幕 |
| `audio` | `data`(Base64), `text` | AI 回复音频 + 文本 |
| `audio_chunk` | `data`(Base64 WAV), `index`, `isLast` | 分片音频 |
| `text` | `content`, `final?` | AI 文本回复 |
| `control` | `action`, `message?`, `timestamp?` | 控制响应 |
| `error` | `message` | 错误 |

---

## 附录 A：核心数据结构

> 均为对外 camelCase；`?` 表示可空/可选。

### ResumeUploadResponse
```ts
{ resume: { id, filename, analyzeStatus }, storage: { fileKey, fileUrl, resumeId }, duplicate }
```

### ResumeListItem
```ts
{ id, filename, fileSize?, uploadedAt, accessCount, latestScore?, lastAnalyzedAt?,
  interviewCount, analyzeStatus, analyzeError? }
```

### ResumeDetail
```ts
{ id, filename, fileSize?, contentType?, storageUrl?, uploadedAt, accessCount, resumeText?,
  analyzeStatus, analyzeError?, analyses: AnalysisHistory[], interviews: InterviewHistoryItem[] }
```

### SkillDTO
```ts
{ id, name, description?, categories: CategoryDTO[], isPreset, sourceJd?, persona?, display? }
```
### CategoryDTO
```ts
{ key, label, priority /* CORE|NORMAL|ALWAYS_ONE */, ref?, shared? }
```

### CreateInterviewRequest
```ts
{ questionCount /* 3-20 */, skillId, difficulty?, resumeId?, resumeText?, forceCreate?,
  llmProviderId?, customCategories?, jdText? }
```
> 注：`forceCreate`（兼容旧 `forceNew`）与 `resumeText` 已对齐前端；`llmProviderId` 仍与前端 `llmProvider` 存在差异，见[附录 B](#附录-b已知契约差异待修复)。

### InterviewSession
```ts
{ sessionId, resumeText, totalQuestions, currentQuestionIndex,
  questions: InterviewQuestion[], status /* CREATED|IN_PROGRESS|COMPLETED|EVALUATED */ }
```
### InterviewQuestion
```ts
{ questionIndex, question, type, category, topicSummary?, userAnswer?, score?, feedback?,
  isFollowUp, parentQuestionIndex? }
```
### SubmitAnswerResponse
```ts
{ hasNextQuestion, nextQuestion?: InterviewQuestion, currentIndex, totalQuestions }
```
### SessionListItem
```ts
{ sessionId, skillId, difficulty, resumeId?, totalQuestions, status,
  evaluateStatus?, evaluateError?, overallScore?, createdAt, completedAt? }
```
### EvaluationResult
```ts
{ sessionId, totalQuestions, overallScore, overallFeedback,
  categoryScores: { category, score, questionCount }[],
  questionDetails: { questionIndex, question, category, userAnswer?, score, feedback }[],
  strengths: string[], improvements: string[],
  referenceAnswers: { questionIndex, question, referenceAnswer, keyPoints[] }[],
  evaluateStatus }
```

### InterviewDetail
```ts
{ id, sessionId, totalQuestions, status, evaluateStatus?, evaluateError?,
  overallScore?, overallFeedback?, createdAt, completedAt?,
  strengths: string[], improvements: string[],
  referenceAnswers: { questionIndex, question, referenceAnswer, keyPoints[] }[],
  answers: { questionIndex, question, category, userAnswer?, score, feedback,
             referenceAnswer?, keyPoints?, answeredAt }[] }
```

### CreateScheduleRequest
```ts
{ companyName, position, interviewTime, interviewType?, meetingLink?, roundNumber?, interviewer?, notes? }
```
### InterviewSchedule
```ts
{ id, companyName, position, interviewTime, interviewType?, meetingLink?, roundNumber,
  interviewer?, notes?, status, createdAt?, updatedAt? }
```
### ParseResponse
```ts
{ success, data?: CreateScheduleRequest, confidence, parseMethod, log }
```

### KnowledgeBaseUploadResponse
```ts
{ knowledgeBase: { id, filename, vectorStatus }, storage: { fileKey, fileUrl, knowledgeBaseId }, duplicate }
```
### KnowledgeBaseItem
```ts
{ id, name, category?, originalFilename, fileSize?, contentType?, uploadedAt, lastAccessedAt,
  accessCount, questionCount, vectorStatus, vectorError?, chunkCount }
```
### KnowledgeBaseStats
```ts
{ totalCount, totalQuestionCount, totalAccessCount, completedCount, processingCount }
```

### RagSession
```ts
{ id, title?, knowledgeBaseIds: number[], createdAt }
```
### RagSessionListItem
```ts
{ id, title?, messageCount, knowledgeBaseNames: string[], updatedAt, isPinned }
```
### RagSessionDetail
```ts
{ id, title?, knowledgeBases: KnowledgeBaseItem[], messages: { id, type, content?, createdAt }[],
  createdAt, updatedAt }
```

### ProviderItem
```ts
{ id, baseUrl, maskedApiKey, model, embeddingModel?, embeddingDimensions, supportsEmbedding,
  temperature?, defaultChatProvider, defaultEmbeddingProvider }
```
### CreateProviderRequest
```ts
{ id, baseUrl, apiKey, model, embeddingModel?, embeddingDimensions?, supportsEmbedding?, temperature? }
```
### UpdateProviderRequest
```ts
{ baseUrl?, apiKey?, model?, embeddingModel?, embeddingDimensions?, supportsEmbedding?, temperature? }
```
### AsrConfig
```ts
{ url, model, maskedApiKey, language, format, sampleRate, enableTurnDetection,
  turnDetectionType, turnDetectionThreshold, turnDetectionSilenceDurationMs }
```
### TtsConfig
```ts
{ model, maskedApiKey, voice, format, sampleRate, mode, languageType, speechRate, volume }
```

### CreateVoiceSessionRequest
```ts
{ roleType?, skillId, difficulty?, resumeId?, customJdText?,
  introEnabled?, techEnabled?, projectEnabled?, hrEnabled?, plannedDuration?, llmProviderId? }
```
### VoiceSession
```ts
{ id, sessionId, userId, roleType, skillId, difficulty, customJdText?, resumeId?,
  introEnabled, techEnabled, projectEnabled, hrEnabled, llmProvider?, currentPhase, status,
  plannedDuration, actualDuration?, startTime, endTime?, createdAt, updatedAt,
  pausedAt?, resumedAt?, evaluateStatus?, webSocketUrl? }
```
### VoiceSessionMeta
```ts
{ id, sessionId, roleType, skillId, status, currentPhase, startTime, endTime?,
  createdAt, updatedAt, actualDuration?, messageCount, evaluateStatus?, evaluateError? }
```
### VoiceMessage
```ts
{ id, sessionId, messageType, phase, userRecognizedText?, aiGeneratedText?, timestamp, sequenceNum }
```
### VoiceEvaluationStatus
```ts
{ evaluateStatus, evaluateError?, evaluation?: {
    sessionId, totalQuestions, overallScore, overallFeedback, strengths[], improvements[],
    answers: { questionIndex, question, category, userAnswer, score, feedback, referenceAnswer?, keyPoints? }[] } }
```

---

## 附录 B：已知契约差异（待修复）

> 以下为终局迁移审查发现的 Python 实现与「复用的 Java 前端契约」不一致项，**文档如实标注**，修复前请前端联调注意。级别沿用审查：Blocker=页面崩溃/契约不符。

| 级别 | 端点 / 字段 | 前端期望 | Python 现状 | 影响 |
|---|---|---|---|---|
| High | 面试/语音创建请求 `llmProvider` | `llmProvider: string`（供应商名） | 字段为 `llmProviderId: int` → **被忽略** | 用户选定的 LLM 供应商被忽略、回退默认 |
| Low | `GET /api/interview/sessions/{id}/report` | 面试报告（`InterviewReport`） | 未实现（前端无页面调用，`/evaluation` 已覆盖数据） | 死端点 |
| Low | `GET /api/knowledgebase/{id}`、`/uncategorized` | 详情 / 未分类列表 | 未实现（前端无页面调用；ADR-0015 死端点清单未收录此二者） | 契约/文档完整性 |
| Low | KB `/query`、`/query/stream`；RAG `/{id}/knowledge-bases`；简历 `/health` | — | 未实现（**已在 ADR-0015 记录为死端点**） | 无（前端无页面调用） |

> 完整证据（file:line 三方比对）见终局迁移审查报告。
