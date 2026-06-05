"""
GR7 Hub Core Module
===================
Базовые классы и утилиты для всей системы.
"""

from .state_manager import StateManager
from .config_loader import ConfigLoader
from .logger import Logger
from .diagnostics import (
    ThreadWatchdog,
    FreezeDetector,
    GlobalExceptionHandler,
    ImportProfiler,
    StartupProfiler,
    setup_faulthandler,
    setup_signal_handlers
)
from .service_states import ServiceState, ServiceHealth, can_transition
from .service_manager import ServiceManager, IService, ServiceInfo
from .bootstrap import BootstrapManager, BootstrapPhase, BootstrapResult, ServiceBootstrapConfig, create_bootstrap_manager
from .async_utils import (
    LockFreeQueue,
    RingBuffer,
    AsyncRingBuffer,
    Snapshot,
    SnapshotStore,
    AsyncTaskGroup,
    run_in_executor,
    Debouncer,
    Throttler,
    timeout_context
)

__all__ = [
    'StateManager', 
    'ConfigLoader', 
    'Logger',
    'ThreadWatchdog',
    'FreezeDetector',
    'GlobalExceptionHandler',
    'ImportProfiler',
    'StartupProfiler',
    'setup_faulthandler',
    'setup_signal_handlers',
    'ServiceState',
    'ServiceHealth',
    'can_transition',
    'ServiceManager',
    'IService',
    'ServiceInfo',
    'BootstrapManager',
    'BootstrapPhase',
    'BootstrapResult',
    'ServiceBootstrapConfig',
    'create_bootstrap_manager',
    'LockFreeQueue',
    'RingBuffer',
    'AsyncRingBuffer',
    'Snapshot',
    'SnapshotStore',
    'AsyncTaskGroup',
    'run_in_executor',
    'Debouncer',
    'Throttler',
    'timeout_context',
]