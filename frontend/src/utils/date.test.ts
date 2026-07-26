import { describe, expect, it } from 'vitest';

import { snapDateTimeToStep } from './date';

describe('snapDateTimeToStep', () => {
  it('已对齐 15 分钟档位时保持不变', () => {
    expect(snapDateTimeToStep('2026-07-26T10:00')).toBe('2026-07-26T10:00');
    expect(snapDateTimeToStep('2026-07-26T10:45')).toBe('2026-07-26T10:45');
  });

  it('分钟四舍五入到最近的 15 分钟档位', () => {
    expect(snapDateTimeToStep('2026-07-26T10:07')).toBe('2026-07-26T10:00');
    expect(snapDateTimeToStep('2026-07-26T10:08')).toBe('2026-07-26T10:15');
    expect(snapDateTimeToStep('2026-07-26T10:38')).toBe('2026-07-26T10:45');
  });

  it('向上归整跨小时时正确进位', () => {
    expect(snapDateTimeToStep('2026-07-26T10:53')).toBe('2026-07-26T11:00');
    expect(snapDateTimeToStep('2026-07-26T23:59')).toBe('2026-07-27T00:00');
  });

  it('支持自定义档位（30 分钟）', () => {
    expect(snapDateTimeToStep('2026-07-26T10:20', 30)).toBe('2026-07-26T10:30');
    expect(snapDateTimeToStep('2026-07-26T10:10', 30)).toBe('2026-07-26T10:00');
  });

  it('空值与非法值原样返回', () => {
    expect(snapDateTimeToStep('')).toBe('');
    expect(snapDateTimeToStep('not-a-date')).toBe('not-a-date');
  });
});
