import type { SkillDTO } from '../api/skill';

export function getTemplateName(skillId: string, skills: SkillDTO[]): string {
  return skills.find(s => s.id === skillId)?.name || skillId;
}

/**
 * 基于当前页面地址构造语音面试 WebSocket 地址（走 vite /ws 代理）。
 * 仅在后端未下发 webSocketUrl 时作兜底，不得硬编码主机端口（#50）。
 */
export function buildVoiceInterviewWsUrl(sessionId: number | string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}/ws/voice-interview/${sessionId}`;
}

/** 对话实录条目（#62：统一类型，避免页面/组件/工具三处重复内联定义）。 */
export interface TranscriptMessage {
  role: 'user' | 'ai';
  text: string;
  id: string;
}

/**
 * 待渲染/落实录的 AI 文本是否与实录**两端** ai 条目重复（#62 渲染层去重）。
 *
 * 后端每次 WS 连接都重投开场白（#57：重连只投递不落库）——重投文本命中实录第一条 ai；
 * 双路径 commit 的相邻重复命中最后一条 ai。仅比对两端而非全历史：
 * 面试官中途逐字重复的合法发言（如追问同一问题）不被误伤。
 * WS 实时消息无 id/sequenceNum，文本即身份。
 */
export function isDuplicateAiText(messages: { role: 'user' | 'ai'; text: string }[], text: string): boolean {
  const normalized = (text || '').trim();
  if (!normalized) {
    return false;
  }
  const aiTexts = messages.filter(msg => msg.role === 'ai').map(msg => msg.text.trim());
  if (aiTexts.length === 0) {
    return false;
  }
  return aiTexts[0] === normalized || aiTexts[aiTexts.length - 1] === normalized;
}
