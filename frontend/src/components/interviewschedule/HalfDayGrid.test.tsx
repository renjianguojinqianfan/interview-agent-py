import { render, screen, within, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { InterviewSchedule } from '../../types/interviewSchedule'
import { HalfDayGrid } from './HalfDayGrid'

function makeSchedule(id: number, interviewTime: string, companyName = `公司${id}`): InterviewSchedule {
  return {
    id,
    companyName,
    position: '后端工程师',
    interviewTime,
    interviewType: 'VIDEO',
    roundNumber: 1,
    status: 'PENDING',
    createdAt: '2026-07-01T00:00:00',
    updatedAt: '2026-07-01T00:00:00',
  }
}

// 2026-07-27 是周一
const MONDAY = new Date('2026-07-27T00:00:00')

describe('HalfDayGrid 周视图（#64 上午/下午两栏）', () => {
  it('渲染 7 天 × 上午/下午区块，空区块保留占位', () => {
    render(<HalfDayGrid view="week" date={MONDAY} interviews={[]} onSelectEvent={() => {}} />)
    // 7 天 × 2 区块 = 上午/下午标签各 7 个
    expect(screen.getAllByText('上午')).toHaveLength(7)
    expect(screen.getAllByText('下午')).toHaveLength(7)
    // 全空：14 个空占位
    expect(screen.getAllByText('无安排')).toHaveLength(14)
  })

  it('11:30 条目在上午区块、12:30 条目在下午区块，且显示起止时间文案', () => {
    render(
      <HalfDayGrid
        view="day"
        date={MONDAY}
        interviews={[
          makeSchedule(1, '2026-07-27T11:30:00', '晨会公司'),
          makeSchedule(2, '2026-07-27T12:30:00', '午后公司'),
        ]}
        onSelectEvent={() => {}}
      />,
    )
    const morning = screen.getByTestId('halfday-morning-2026-07-27')
    const afternoon = screen.getByTestId('halfday-afternoon-2026-07-27')
    expect(within(morning).getByText('晨会公司')).toBeInTheDocument()
    expect(within(morning).getByText('11:30 - 12:00')).toBeInTheDocument()
    expect(within(afternoon).getByText('午后公司')).toBeInTheDocument()
    expect(within(afternoon).getByText('12:30 - 13:00')).toBeInTheDocument()
  })

  it('点击条目回调 onSelectEvent 并携带该条目', () => {
    const onSelectEvent = vi.fn()
    const schedule = makeSchedule(7, '2026-07-27T14:00:00', '点击公司')
    render(<HalfDayGrid view="day" date={MONDAY} interviews={[schedule]} onSelectEvent={onSelectEvent} />)

    fireEvent.click(screen.getByText('点击公司'))

    expect(onSelectEvent).toHaveBeenCalledTimes(1)
    expect(onSelectEvent).toHaveBeenCalledWith(schedule)
  })
})
