# Interview Agent

智能面试官平台，提供简历分析、模拟面试（文字/语音）、RAG 知识库问答等能力。

## Language

### 参与者

**Interviewee**:
通过平台进行模拟面试、上传简历、使用知识库问答的用户。
_Avoid_: 用户（过于宽泛）、Candidate

**Admin**:
配置 LLM 供应商和语音服务的用户。
_Avoid_: 超级用户、Administrator

### 简历

**Resume**:
面试者上传的简历文件（PDF/DOCX/TXT/MD），是简历分析和定制出题的依据。
_Avoid_: CV

**ResumeAnalysis**:
LLM 对简历生成的分析结果，包含综合评分、各维度评分、优势、建议。
_Avoid_: 简历评分（Analysis 包含评分但不限于评分）、Grading

### 文字面试

**InterviewSession**:
面试者与 AI 之间的一次模拟文字面试会话。
_Avoid_: 面试（过于宽泛）、Mock Interview

**InterviewQuestion**:
AI 根据简历、技能或方向生成的面试题。
_Avoid_: 题目、Problem

**InterviewAnswer**:
面试者对一道 InterviewQuestion 的回答记录。
_Avoid_: 回复、Response

**InterviewEvaluation**:
面试会话的评估结果，包含逐题反馈和总体评价。
_Avoid_: 面试评分（Evaluation 是会话级评估，非单次评分）、Score

**Skill**:
面试的可选方向领域（如"Spring Boot"、"数据库设计"），用于出题定向。每个 Skill 含多个 SkillCategory（考察方向，如 JAVA/MYSQL/REDIS），按 CategoryPriority（CORE/NORMAL/ALWAYS_ONE）分配题量。
_Avoid_: 技能（在业务上下文中用 Skill 或"方向"）、Competency

**SkillCategory**:
Skill 内的考察方向（如 java-backend 技能下的 JAVA、MYSQL、REDIS），携带参考基线（ref 文件名）与优先级，是出题定向与题量分配的最小单元。
_Avoid_: 分类（用 SkillCategory 精确指代）、Category

**allocation**:
题量分配算法：按 CategoryPriority 三阶段分配 total_questions--ALWAYS_ONE 保底各 1 题 -> 全覆盖各 1 题（CORE 优先）-> 剩余按 CORE->NORMAL 轮转。
_Avoid_: 分配（用 allocation 精确指代）、Distribution

**JD (Job Description)**:
面试者提供的岗位描述文本，用于定制出题方向。
_Avoid_: 招聘要求、Job Posting

### 面试日程

**InterviewSchedule**:
面试者安排的真实面试日程（非模拟）。
_Avoid_: 面试安排、Appointment

### 知识库与 RAG

**KnowledgeBase**:
面试者上传的知识库文件，是 RAG 问答检索的数据来源。
_Avoid_: 文档库、Document Store

**RagChatSession**:
基于知识库的流式问答会话。
_Avoid_: 聊天（过于宽泛）、Chat

### 语音面试

**VoiceInterviewSession**:
实时语音面试会话，包含语音识别和语音合成。
_Avoid_: 语音通话、Voice Call

**InterviewPhase**:
语音面试的四个阶段：INTRO -> TECH -> PROJECT -> HR，每个阶段有独立的时长和题数约束。
_Avoid_: 轮次（Phase 是面试阶段，非单轮对话）、Round

### 状态

**SessionStatus**:
文字面试会话生命周期：CREATED -> IN_PROGRESS -> COMPLETED -> EVALUATED。
_Avoid_: 会话状态（用 SessionStatus 精确指代）

**VectorStatus**:
vector_store 内向量数据的两阶段：pending（待定，元数据带 kb_vector_job_id）-> promoted（正式，元数据带 kb_id，可检索）。知识库行的向量化进度字段 KnowledgeBase.vector_status 复用 AsyncTaskStatus（COMPLETED 即 promoted）。
_Avoid_: 向量状态

**AsyncTaskStatus**:
异步任务状态机，复用于简历分析、知识库向量化、语音评估等 Stream 消费者：PENDING -> PROCESSING -> COMPLETED / FAILED。
_Avoid_: 任务状态（用 AsyncTaskStatus 精确指代）

### LLM 配置

**LlmProvider**:
LLM 供应商配置（base_url、api_key、model），是创建 LLM 客户端的依据。
_Avoid_: AI 配置（过于宽泛）、Model Config
