// frontend/src/components/interviewschedule/HalfDayGrid.tsx

import React from 'react';
import dayjs from 'dayjs';
import type { InterviewSchedule } from '../../types/interviewSchedule';
import { groupByHalfDay } from '../../utils/interviewSchedule';
import { InterviewEvent } from './InterviewEvent';

interface HalfDayGridProps {
  view: 'week' | 'day';
  date: Date;
  interviews: InterviewSchedule[];
  onSelectEvent: (interview: InterviewSchedule) => void;
}

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

/** 条目卡片：起止时间文案 + 复用 InterviewEvent 状态配色（end = start+30min，与月视图 events 映射一致）。 */
function ScheduleItem({
  interview,
  onSelect,
}: {
  interview: InterviewSchedule;
  onSelect: (interview: InterviewSchedule) => void;
}) {
  const start = dayjs(interview.interviewTime);
  const end = start.add(30, 'minute');
  return (
    // div role=button 而非原生 button：内容含块级卡片（InterviewEvent），button 仅允许 phrasing content
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(interview)}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(interview);
        }
      }}
      className="w-full text-left cursor-pointer"
    >
      <div className="text-[11px] font-medium text-slate-500 dark:text-slate-400 mb-0.5">
        {start.format('HH:mm')} - {end.format('HH:mm')}
      </div>
      <InterviewEvent event={interview} />
    </div>
  );
}

/** 半天区块：上午/下午标签 + 条目列表；无日程保留空占位（每天结构一致，扫一眼即知哪个半天有空）。 */
function HalfDayBlock({
  label,
  slot,
  day,
  items,
  onSelect,
}: {
  label: string;
  slot: 'morning' | 'afternoon';
  day: dayjs.Dayjs;
  items: InterviewSchedule[];
  onSelect: (interview: InterviewSchedule) => void;
}) {
  return (
    <div
      data-testid={`halfday-${slot}-${day.format('YYYY-MM-DD')}`}
      className="flex-1 min-h-[96px] rounded-xl border border-slate-200/70 dark:border-slate-700/60 bg-slate-50/50 dark:bg-slate-800/40 p-2 space-y-2"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
        {label}
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-slate-300 dark:text-slate-600 select-none py-3 text-center">无安排</div>
      ) : (
        items.map(interview => <ScheduleItem key={interview.id} interview={interview} onSelect={onSelect} />)
      )}
    </div>
  );
}

/**
 * 上午/下午两栏日历（#64）：周视图 7 列、日视图单列，替代 react-big-calendar 逐小时时间轴。
 * 纯展示层——归栏逻辑见 utils/interviewSchedule.groupByHalfDay；调整时间走编辑弹窗（15 分钟档位，#53）。
 */
export const HalfDayGrid: React.FC<HalfDayGridProps> = ({ view, date, interviews, onSelectEvent }) => {
  const days =
    view === 'week'
      ? Array.from({ length: 7 }, (_, i) => dayjs(date).startOf('week').add(i, 'day'))
      : [dayjs(date)];

  return (
    <div className={view === 'week' ? 'grid grid-cols-7 gap-3' : 'grid grid-cols-1 gap-3'}>
      {days.map(day => {
        const isToday = day.isSame(dayjs(), 'day');
        const { morning, afternoon } = groupByHalfDay(interviews, day.toDate());
        return (
          <div key={day.format('YYYY-MM-DD')} className="flex flex-col gap-2">
            <div
              className={`text-center text-xs font-semibold rounded-lg py-1.5 ${
                isToday
                  ? 'bg-primary-500/10 text-primary-600 dark:text-primary-300 border border-primary-300/50'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {WEEKDAY_LABELS[day.day()]} {day.format('MM-DD')}
            </div>
            <HalfDayBlock label="上午" slot="morning" day={day} items={morning} onSelect={onSelectEvent} />
            <HalfDayBlock label="下午" slot="afternoon" day={day} items={afternoon} onSelect={onSelectEvent} />
          </div>
        );
      })}
    </div>
  );
};
