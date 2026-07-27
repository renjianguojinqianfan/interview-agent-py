import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import RealtimeSubtitle from './RealtimeSubtitle'

const OPENING = '请先做个自我介绍。'

/** #62 场景：恢复会话后实录已有开场白（非末尾），WS 重连触发后端重投开场白播报 */
const RESTORED_MESSAGES = [
  { role: 'ai' as const, text: OPENING, id: 'ai-1' },
  { role: 'user' as const, text: '我叫张三。', id: 'user-1' },
  { role: 'ai' as const, text: '讲讲你最有挑战的项目？', id: 'ai-2' },
]

describe('RealtimeSubtitle 实录去重（#62）', () => {
  it('重投的开场白已存在于实录任意位置时，播报中不渲染第二条相同文本', () => {
    render(
      <RealtimeSubtitle
        messages={RESTORED_MESSAGES}
        userText=""
        aiText={OPENING}
        isAiSpeaking={true}
      />,
    )
    // 实录条目 1 条 + 活动气泡 0 条 = 面板中开场白文本仅出现 1 次
    expect(screen.getAllByText(OPENING)).toHaveLength(1)
  })

  it('全新 AI 文本播报时活动气泡正常显示（去重不误伤正常流）', () => {
    render(
      <RealtimeSubtitle
        messages={RESTORED_MESSAGES}
        userText=""
        aiText="你如何做技术选型？"
        isAiSpeaking={true}
      />,
    )
    expect(screen.getByText('你如何做技术选型？')).toBeInTheDocument()
  })

  it('播报文本与实录最后一条 ai 相同时不重复渲染（既有行为回归守卫）', () => {
    render(
      <RealtimeSubtitle
        messages={RESTORED_MESSAGES}
        userText=""
        aiText="讲讲你最有挑战的项目？"
        isAiSpeaking={true}
      />,
    )
    expect(screen.getAllByText('讲讲你最有挑战的项目？')).toHaveLength(1)
  })
})
