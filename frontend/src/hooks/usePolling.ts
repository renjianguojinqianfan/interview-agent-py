import { useEffect, useRef, useCallback } from 'react';

interface UsePollingOptions {
  /** 轮询回调函数 */
  callback: () => Promise<void> | void;
  /** 初始轮询间隔（毫秒） */
  interval: number;
  /** 最大轮询间隔（毫秒），退避上限 */
  maxInterval?: number;
  /** 是否启用轮询 */
  enabled?: boolean;
  /** 退避倍数，默认 2 */
  backoffMultiplier?: number;
}

interface UsePollingReturn {
  /** 手动触发一次轮询并重置退避 */
  trigger: () => void;
  /** 当前实际轮询间隔 */
  currentInterval: number;
}

/**
 * 指数退避轮询 hook：成功时重置到初始间隔，失败时翻倍直到上限。
 */
export function usePolling({
  callback,
  interval,
  maxInterval = 30000,
  enabled = true,
  backoffMultiplier = 2,
}: UsePollingOptions): UsePollingReturn {
  const currentIntervalRef = useRef(interval);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const callbackRef = useRef(callback);
  const mountedRef = useRef(true);

  // 保持 callback ref 最新
  callbackRef.current = callback;

  const clearTimer = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const scheduleNext = useCallback(() => {
    clearTimer();
    timeoutRef.current = setTimeout(async () => {
      try {
        await callbackRef.current();
        // 成功：重置到初始间隔
        currentIntervalRef.current = interval;
      } catch {
        // 失败：指数退避
        currentIntervalRef.current = Math.min(
          currentIntervalRef.current * backoffMultiplier,
          maxInterval,
        );
      }
      if (mountedRef.current) {
        scheduleNext();
      }
    }, currentIntervalRef.current);
  }, [interval, maxInterval, backoffMultiplier, clearTimer]);

  const trigger = useCallback(() => {
    currentIntervalRef.current = interval;
    clearTimer();
    // 立即执行一次
    Promise.resolve(callbackRef.current())
      .then(() => {
        currentIntervalRef.current = interval;
      })
      .catch(() => {
        currentIntervalRef.current = Math.min(interval * backoffMultiplier, maxInterval);
      })
      .finally(() => {
        if (mountedRef.current) {
          scheduleNext();
        }
      });
  }, [interval, maxInterval, backoffMultiplier, clearTimer, scheduleNext]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) {
      scheduleNext();
    }
    return () => {
      mountedRef.current = false;
      clearTimer();
    };
  }, [enabled, scheduleNext, clearTimer]);

  return { trigger, currentInterval: currentIntervalRef.current };
}
