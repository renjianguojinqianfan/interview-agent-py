import { describe, expect, it } from 'vitest'

import type { InterviewSchedule } from '../types/interviewSchedule'
import { groupByHalfDay } from './interviewSchedule'

function makeSchedule(id: number, interviewTime: string): InterviewSchedule {
  return {
    id,
    companyName: `公司${id}`,
    position: '后端工程师',
    interviewTime,
    interviewType: 'VIDEO',
    roundNumber: 1,
    status: 'PENDING',
    createdAt: '2026-07-01T00:00:00',
    updatedAt: '2026-07-01T00:00:00',
  }
}

const DAY = new Date('2026-07-27T00:00:00')

describe('groupByHalfDay（#64 上午/下午归栏）', () => {
  it('11:30 开始归上午，12:30 开始归下午（按开始时间归栏）', () => {
    const { morning, afternoon } = groupByHalfDay(
      [makeSchedule(1, '2026-07-27T11:30:00'), makeSchedule(2, '2026-07-27T12:30:00')],
      DAY,
    )
    expect(morning.map(i => i.id)).toEqual([1])
    expect(afternoon.map(i => i.id)).toEqual([2])
  })

  it('12:00 整点归下午（分界点）', () => {
    const { morning, afternoon } = groupByHalfDay([makeSchedule(1, '2026-07-27T12:00:00')], DAY)
    expect(morning).toHaveLength(0)
    expect(afternoon.map(i => i.id)).toEqual([1])
  })

  it('晚间条目落入下午栏（不设晚间栏）', () => {
    const { afternoon } = groupByHalfDay([makeSchedule(1, '2026-07-27T20:00:00')], DAY)
    expect(afternoon.map(i => i.id)).toEqual([1])
  })

  it('栏内按开始时间升序', () => {
    const { afternoon } = groupByHalfDay(
      [
        makeSchedule(1, '2026-07-27T16:00:00'),
        makeSchedule(2, '2026-07-27T13:00:00'),
        makeSchedule(3, '2026-07-27T14:30:00'),
      ],
      DAY,
    )
    expect(afternoon.map(i => i.id)).toEqual([2, 3, 1])
  })

  it('非当天条目被过滤', () => {
    const { morning, afternoon } = groupByHalfDay(
      [makeSchedule(1, '2026-07-26T10:00:00'), makeSchedule(2, '2026-07-28T14:00:00')],
      DAY,
    )
    expect(morning).toHaveLength(0)
    expect(afternoon).toHaveLength(0)
  })

  it('无效时间条目被过滤，空输入两栏皆空', () => {
    const { morning, afternoon } = groupByHalfDay([makeSchedule(1, 'not-a-date')], DAY)
    expect(morning).toHaveLength(0)
    expect(afternoon).toHaveLength(0)

    const empty = groupByHalfDay([], DAY)
    expect(empty.morning).toHaveLength(0)
    expect(empty.afternoon).toHaveLength(0)
  })
})
