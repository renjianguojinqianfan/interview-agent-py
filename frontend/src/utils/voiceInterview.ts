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
