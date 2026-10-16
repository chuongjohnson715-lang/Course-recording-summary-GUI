"""重试助手（解决 C-11：瞬时故障导致任务永久 FAILED）。

只用于「可安全重复执行」的操作：调用 LLM、写 Notion、ffmpeg 解码。
绝不要用在「改名」这种非幂等操作上（重试会二次改名）。
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    delay: float = 5.0,
    backoff: float = 2.0,
    on_retry: Callable[[int, Exception], None] | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """执行 fn，失败按 attempts/delay/backoff 重试；最终失败抛出最后一次异常。"""
    current_delay = delay
    last_exc: BaseException | None = None

    for attempt in range(1, max(1, attempts) + 1):
        try:
            return fn()
        except retry_on as exc:  # type: ignore[misc]
            last_exc = exc
            if attempt >= attempts:
                break
            if on_retry:
                on_retry(attempt, exc)
            time.sleep(current_delay)
            current_delay *= backoff

    assert last_exc is not None
    raise last_exc
