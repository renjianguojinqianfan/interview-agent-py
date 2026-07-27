import { describe, expect, it } from 'vitest'

import { isDuplicateAiText } from './voiceInterview'

const MSGS = [
  { role: 'ai' as const, text: '请先做个自我介绍。', id: 'ai-1' },
  { role: 'user' as const, text: '我叫张三。', id: 'user-1' },
  { role: 'ai' as const, text: '为什么选择我们公司？', id: 'ai-2' },
  { role: 'user' as const, text: '因为技术氛围好。', id: 'user-2' },
  { role: 'ai' as const, text: '讲讲你最有挑战的项目？', id: 'ai-3' },
]

describe('isDuplicateAiText（#62 实录去重判定：仅两端比对）', () => {
  it('命中第一条 ai（重连重投的开场白场景）', () => {
    expect(isDuplicateAiText(MSGS, '请先做个自我介绍。')).toBe(true)
  })

  it('命中最后一条 ai（相邻重复 commit 场景）', () => {
    expect(isDuplicateAiText(MSGS, '讲讲你最有挑战的项目？')).toBe(true)
  })

  it('中间位置的 ai 条目不算命中——面试官中途逐字重复的合法发言不被误伤', () => {
    expect(isDuplicateAiText(MSGS, '为什么选择我们公司？')).toBe(false)
  })

  it('trim 后比对：首尾空白差异不影响命中', () => {
    expect(isDuplicateAiText(MSGS, '  请先做个自我介绍。 ')).toBe(true)
  })

  it('user 条目文本相同不算命中（只按 ai 条目去重）', () => {
    expect(isDuplicateAiText(MSGS, '我叫张三。')).toBe(false)
  })

  it('空文本与未命中文本返回 false', () => {
    expect(isDuplicateAiText(MSGS, '')).toBe(false)
    expect(isDuplicateAiText(MSGS, '完全新的问题')).toBe(false)
    expect(isDuplicateAiText([], '请先做个自我介绍。')).toBe(false)
  })
})
