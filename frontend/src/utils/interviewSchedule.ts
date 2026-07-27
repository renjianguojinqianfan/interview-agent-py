// frontend/src/utils/interviewSchedule.ts

import dayjs from 'dayjs';
import type { InterviewSchedule } from '../types/interviewSchedule';

export interface HalfDayGroups {
  morning: InterviewSchedule[];
  afternoon: InterviewSchedule[];
}

/**
 * 按上午/下午归栏指定日期的日程（#64：12:00 分界，替代逐小时时间轴）。
 *
 * 按**开始时间**归栏：hour < 12 归上午（11:30→上午），12:00 起归下午；
 * 晚间条目自然落入下午栏（个人使用场景不设晚间栏）。栏内按开始时间升序。
 * 非当天与无效时间条目被过滤。
 */
export function groupByHalfDay(interviews: InterviewSchedule[], day: Date): HalfDayGroups {
  const target = dayjs(day);
  const sameDay = interviews
    .filter(interview => {
      const t = dayjs(interview.interviewTime);
      return t.isValid() && t.isSame(target, 'day');
    })
    .sort((a, b) => dayjs(a.interviewTime).valueOf() - dayjs(b.interviewTime).valueOf());

  return {
    morning: sameDay.filter(interview => dayjs(interview.interviewTime).hour() < 12),
    afternoon: sameDay.filter(interview => dayjs(interview.interviewTime).hour() >= 12),
  };
}
