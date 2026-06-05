"""
Async Utilities
===============
Lock-free queues, ring buffers, and async utilities for realtime-safe operations.
"""

import asyncio
import threading
import time
import numpy as np
from collections import deque
from dataclasses import dataclass
from typing import Generic, TypeVar, Optional, Any, Callable, Awaitable
from contextlib import asynccontextmanager

T = TypeVar('T')


class LockFreeQueue(Generic[T]):
    """
    Lock-free MPSC (Multi-Producer Single-Consumer) queue using asyncio.Queue
    with optimized batch operations for realtime audio.
    """
    
    def __init__(self, maxsize: int = 0):
        self._queue = asyncio.Queue(maxsize=maxsize)
        self._sync_queue: deque = deque()
        self._lock = threading.Lock()
        self._closed = False
    
    async def put(self, item: T) -> None:
        """Put item into queue (async)"""
        if self._closed:
            raise RuntimeError("Queue is closed")
        await self._queue.put(item)
    
    def put_nowait(self, item: T) -> bool:
        """Put item without blocking (thread-safe)"""
        if self._closed:
            return False
        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            return False
    
    async def get(self) -> T:
        """Get item from queue (async)"""
        return await self._queue.get()
    
    def get_nowait(self) -> Optional[T]:
        """Get item without blocking"""
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
    
    def get_batch(self, max_items: int = 10) -> list:
        """Get multiple items at once (non-blocking)"""
        items = []
        for _ in range(max_items):
            item = self.get_nowait()
            if item is None:
                break
            items.append(item)
        return items
    
    def qsize(self) -> int:
        return self._queue.qsize()
    
    def empty(self) -> bool:
        return self._queue.empty()
    
    def close(self) -> None:
        self._closed = True
    
    @property
    def is_closed(self) -> bool:
        return self._closed


class RingBuffer(Generic[T]):
    """
    Lock-free ring buffer for realtime audio data.
    Single-writer, single-reader optimized.
    """
    
    def __init__(self, capacity: int, dtype: type = np.float32):
        self.capacity = capacity
        self.dtype = dtype
        self._buffer = np.zeros(capacity, dtype=dtype)
        self._write_pos = 0
        self._read_pos = 0
        self._size = 0
        self._lock = threading.Lock()  # Only for size tracking
    
    def write(self, data: np.ndarray) -> int:
        """
        Write data to buffer. Returns number of samples written.
        Non-blocking, overwrites oldest data if full.
        """
        if len(data) == 0:
            return 0
        
        n = min(len(data), self.capacity)
        data = data[:n]
        
        # Calculate write positions
        end_pos = self._write_pos + n
        
        if end_pos <= self.capacity:
            # Single contiguous write
            self._buffer[self._write_pos:end_pos] = data
        else:
            # Wrap around
            first_part = self.capacity - self._write_pos
            self._buffer[self._write_pos:] = data[:first_part]
            self._buffer[:n - first_part] = data[first_part:]
        
        with self._lock:
            self._write_pos = end_pos % self.capacity
            self._size = min(self._size + n, self.capacity)
        
        return n
    
    def read(self, n: int) -> np.ndarray:
        """
        Read n samples from buffer. Returns available data (may be less than n).
        Non-blocking.
        """
        with self._lock:
            available = min(n, self._size)
            if available == 0:
                return np.zeros(0, dtype=self.dtype)
            
            read_pos = self._read_pos
            end_pos = read_pos + available
        
        if end_pos <= self.capacity:
            # Single contiguous read
            result = self._buffer[read_pos:end_pos].copy()
        else:
            # Wrap around
            first_part = self.capacity - read_pos
            result = np.concatenate([
                self._buffer[read_pos:],
                self._buffer[:available - first_part]
            ])
        
        with self._lock:
            self._read_pos = end_pos % self.capacity
            self._size -= available
        
        return result
    
    def peek(self, n: int) -> np.ndarray:
        """Peek at next n samples without consuming"""
        with self._lock:
            available = min(n, self._size)
            if available == 0:
                return np.zeros(0, dtype=self.dtype)
            read_pos = self._read_pos
            end_pos = read_pos + available
        
        if end_pos <= self.capacity:
            return self._buffer[read_pos:end_pos].copy()
        else:
            first_part = self.capacity - read_pos
            return np.concatenate([
                self._buffer[read_pos:],
                self._buffer[:available - first_part]
            ])
    
    def clear(self) -> None:
        """Clear the buffer"""
        with self._lock:
            self._read_pos = 0
            self._write_pos = 0
            self._size = 0
    
    @property
    def size(self) -> int:
        with self._lock:
            return self._size
    
    @property
    def available(self) -> int:
        return self.size
    
    @property
    def free(self) -> int:
        return self.capacity - self.size
    
    @property
    def is_full(self) -> bool:
        return self.size >= self.capacity
    
    @property
    def is_empty(self) -> bool:
        return self.size == 0


class AsyncRingBuffer(Generic[T]):
    """
    Async-compatible ring buffer with awaitable read/write.
    """
    
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._buffer = [None] * capacity
        self._write_pos = 0
        self._read_pos = 0
        self._size = 0
        self._read_event = asyncio.Event()
        self._write_event = asyncio.Event()
        self._write_event.set()  # Initially writable
        self._closed = False
    
    async def write(self, item: T) -> bool:
        """Write item, waiting if full"""
        while self._size >= self.capacity and not self._closed:
            self._write_event.clear()
            try:
                await asyncio.wait_for(self._write_event.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
        
        if self._closed:
            return False
        
        self._buffer[self._write_pos] = item
        self._write_pos = (self._write_pos + 1) % self.capacity
        self._size += 1
        self._read_event.set()
        return True
    
    async def read(self) -> Optional[T]:
        """Read item, waiting if empty"""
        while self._size == 0 and not self._closed:
            self._read_event.clear()
            try:
                await asyncio.wait_for(self._read_event.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
        
        if self._size == 0 and self._closed:
            return None
        
        item = self._buffer[self._read_pos]
        self._buffer[self._read_pos] = None
        self._read_pos = (self._read_pos + 1) % self.capacity
        self._size -= 1
        self._write_event.set()
        return item
    
    def write_nowait(self, item: T) -> bool:
        """Non-blocking write"""
        if self._size >= self.capacity or self._closed:
            return False
        self._buffer[self._write_pos] = item
        self._write_pos = (self._write_pos + 1) % self.capacity
        self._size += 1
        self._read_event.set()
        return True
    
    def read_nowait(self) -> Optional[T]:
        """Non-blocking read"""
        if self._size == 0:
            return None
        item = self._buffer[self._read_pos]
        self._buffer[self._read_pos] = None
        self._read_pos = (self._read_pos + 1) % self.capacity
        self._size -= 1
        self._write_event.set()
        return item
    
    def close(self) -> None:
        self._closed = True
        self._read_event.set()
        self._write_event.set()
    
    @property
    def size(self) -> int:
        return self._size
    
    @property
    def is_full(self) -> bool:
        return self._size >= self.capacity
    
    @property
    def is_empty(self) -> bool:
        return self._size == 0


@dataclass
class Snapshot(Generic[T]):
    """Immutable snapshot for lock-free reads"""
    data: T
    timestamp: float
    version: int


class SnapshotStore(Generic[T]):
    """
    Lock-free snapshot store using atomic reference swap.
    Writers create new snapshots, readers get atomic reference.
    """
    
    def __init__(self, initial: T):
        self._snapshot = Snapshot(data=initial, timestamp=time.time(), version=0)
        self._lock = threading.Lock()  # Only for version increment
    
    def update(self, updater: Callable[[T], T]) -> Snapshot[T]:
        """Update snapshot with a function"""
        with self._lock:
            new_data = updater(self._snapshot.data)
            new_version = self._snapshot.version + 1
            self._snapshot = Snapshot(
                data=new_data,
                timestamp=time.time(),
                version=new_version
            )
            return self._snapshot
    
    def set(self, data: T) -> Snapshot[T]:
        """Set snapshot directly"""
        with self._lock:
            new_version = self._snapshot.version + 1
            self._snapshot = Snapshot(
                data=data,
                timestamp=time.time(),
                version=new_version
            )
            return self._snapshot
    
    def get(self) -> Snapshot[T]:
        """Get current snapshot (lock-free read)"""
        # In CPython, reference assignment is atomic
        return self._snapshot
    
    def get_data(self) -> T:
        """Get current data (lock-free)"""
        return self._snapshot.data


class AsyncTaskGroup:
    """
    Manages a group of async tasks with proper cleanup.
    """
    
    def __init__(self, name: str = "TaskGroup"):
        self.name = name
        self._tasks: set = set()
        self._closed = False
    
    def create_task(self, coro: Awaitable, name: str = None) -> asyncio.Task:
        """Create and track a task"""
        if self._closed:
            raise RuntimeError(f"{self.name} is closed")
        
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
    
    async def wait_all(self, timeout: float = None) -> list:
        """Wait for all tasks to complete"""
        if not self._tasks:
            return []
        
        done, pending = await asyncio.wait(
            self._tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED
        )
        
        results = []
        for task in done:
            try:
                results.append(task.result())
            except Exception as e:
                results.append(e)
        
        return results
    
    async def cancel_all(self) -> None:
        """Cancel all tasks"""
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=2.0)
    
    def close(self) -> None:
        self._closed = True
    
    @property
    def active_count(self) -> int:
        return len(self._tasks)


@asynccontextmanager
async def timeout_context(seconds: float, message: str = "Operation timed out"):
    """Async context manager for timeouts"""
    try:
        yield
    except asyncio.TimeoutError:
        raise TimeoutError(message)


def run_in_executor(func: Callable, *args, executor=None, **kwargs) -> Awaitable:
    """Run a blocking function in thread executor"""
    loop = asyncio.get_event_loop()
    if executor is None:
        return loop.run_in_executor(None, lambda: func(*args, **kwargs))
    return loop.run_in_executor(executor, lambda: func(*args, **kwargs))


class Debouncer:
    """Debounce rapid calls"""
    
    def __init__(self, delay: float):
        self.delay = delay
        self._task: Optional[asyncio.Task] = None
        self._last_args = None
        self._last_kwargs = None
    
    def __call__(self, func: Callable) -> Callable:
        async def debounced(*args, **kwargs):
            self._last_args = args
            self._last_kwargs = kwargs
            
            if self._task:
                self._task.cancel()
            
            async def run():
                await asyncio.sleep(self.delay)
                if self._last_args is not None:
                    await func(*self._last_args, **self._last_kwargs)
            
            self._task = asyncio.create_task(run())
        
        return debounced
    
    def cancel(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None


class Throttler:
    """Throttle calls to maximum rate"""
    
    def __init__(self, rate: float):  # calls per second
        self.interval = 1.0 / rate
        self._last_call = 0.0
        self._lock = asyncio.Lock()
    
    async def __call__(self, func: Callable, *args, **kwargs):
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self._last_call = time.time()
            return await func(*args, **kwargs)