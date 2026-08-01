import { request } from './request';

/** 自适应面试 Agent API */

export interface AdaptiveQuestionDTO {
  question: string;
  category: string;
  difficulty: string;
  question_index: number;
}

export interface AdaptiveSessionDTO {
  session_id: string;
  skill_id: string;
  difficulty: string;
  turn_count: number;
  max_turns: number;
  current_question: AdaptiveQuestionDTO | null;
  finished: boolean;
  category_scores: Record<string, number>;
  decision_trace?: Record<string, unknown>[] | null;
  pending_approval?: Record<string, unknown> | null;
}

export interface AdaptiveAnswerResultDTO {
  score: number | null;
  feedback: string | null;
  next_question: AdaptiveQuestionDTO | null;
  finished: boolean;
  difficulty_changed: boolean;
  new_difficulty: string | null;
  pending_approval?: Record<string, unknown> | null;
}

export interface CreateAdaptiveSessionRequest {
  skill_id?: string;
  difficulty?: string;
  resume_text?: string;
  max_turns?: number;
  llm_provider?: string | null;
}

export interface SubmitAdaptiveAnswerRequest {
  answer: string;
}

export interface ResumeSessionRequest {
  approved: boolean;
}

export const agentInterviewApi = {
  /**
   * 创建自适应面试会话
   */
  async createSession(req: CreateAdaptiveSessionRequest): Promise<AdaptiveSessionDTO> {
    return request.post<AdaptiveSessionDTO>('/api/agent/interview/sessions', req, {
      timeout: 180000,
    });
  },

  /**
   * 获取会话状态
   */
  async getSession(sessionId: string): Promise<AdaptiveSessionDTO> {
    return request.get<AdaptiveSessionDTO>(`/api/agent/interview/sessions/${sessionId}`);
  },

  /**
   * 提交答案
   */
  async submitAnswer(sessionId: string, req: SubmitAdaptiveAnswerRequest): Promise<AdaptiveAnswerResultDTO> {
    return request.post<AdaptiveAnswerResultDTO>(
      `/api/agent/interview/sessions/${sessionId}/answer`,
      req,
      { timeout: 180000 },
    );
  },

  /**
   * 恢复被 interrupt 暂停的会话（Human-in-the-Loop 审批）
   */
  async resumeSession(sessionId: string, req: ResumeSessionRequest): Promise<AdaptiveAnswerResultDTO> {
    return request.post<AdaptiveAnswerResultDTO>(
      `/api/agent/interview/sessions/${sessionId}/resume`,
      req,
    );
  },

  /**
   * 获取面试结果报告
   */
  async getReport(sessionId: string): Promise<AdaptiveAnswerResultDTO> {
    return request.get<AdaptiveAnswerResultDTO>(`/api/agent/interview/sessions/${sessionId}/result`);
  },
};