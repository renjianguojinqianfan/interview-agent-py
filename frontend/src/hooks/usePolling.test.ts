import assert from 'node:assert/strict';
import { afterEach, beforeEach, describe, test, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePolling } from './usePolling';

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('enabled 时按间隔调用 callback', async () => {
    const callback = vi.fn().mockResolvedValue(undefined);
    renderHook(() =>
      usePolling({ callback, interval: 1000 }),
    );

    // 第一次触发
    await vi.advanceTimersByTimeAsync(1000);
    assert.equal(callback.mock.calls.length, 1);

    // 第二次触发
    await vi.advanceTimersByTimeAsync(1000);
    assert.equal(callback.mock.calls.length, 2);
  });

  test('disabled 时不调用 callback', async () => {
    const callback = vi.fn().mockResolvedValue(undefined);
    renderHook(() =>
      usePolling({ callback, interval: 1000, enabled: false }),
    );

    await vi.advanceTimersByTimeAsync(3000);
    assert.equal(callback.mock.calls.length, 0);
  });

  test('失败时指数退避', async () => {
    const callback = vi.fn().mockRejectedValue(new Error('fail'));
    renderHook(() =>
      usePolling({ callback, interval: 1000, maxInterval: 8000, backoffMultiplier: 2 }),
    );

    // 第一次：1000ms 后调用，失败
    await vi.advanceTimersByTimeAsync(1000);
    assert.equal(callback.mock.calls.length, 1);

    // 退避到 2000ms
    await vi.advanceTimersByTimeAsync(1000);
    assert.equal(callback.mock.calls.length, 1); // 还没到
    await vi.advanceTimersByTimeAsync(1000);
    assert.equal(callback.mock.calls.length, 2); // 2000ms 后调用

    // 退避到 4000ms
    await vi.advanceTimersByTimeAsync(4000);
    assert.equal(callback.mock.calls.length, 3);
  });

  test('成功后重置间隔', async () => {
    let shouldFail = true;
    const callback = vi.fn().mockImplementation(async () => {
      if (shouldFail) throw new Error('fail');
    });

    renderHook(() =>
      usePolling({ callback, interval: 1000, maxInterval: 8000, backoffMultiplier: 2 }),
    );

    // 第一次：失败，退避到 2000ms
    await vi.advanceTimersByTimeAsync(1000);
    assert.equal(callback.mock.calls.length, 1);

    // 先切换为成功模式，再推进 2000ms
    shouldFail = false;
    await vi.advanceTimersByTimeAsync(2000);
    assert.equal(callback.mock.calls.length, 2);

    // 成功后重置回 1000ms
    await vi.advanceTimersByTimeAsync(1000);
    assert.equal(callback.mock.calls.length, 3);
  });

  test('卸载时清理定时器', async () => {
    const callback = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() =>
      usePolling({ callback, interval: 1000 }),
    );

    unmount();
    await vi.advanceTimersByTimeAsync(5000);
    assert.equal(callback.mock.calls.length, 0);
  });
});
