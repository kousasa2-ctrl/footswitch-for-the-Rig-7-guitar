"""
Diagnostics & Watchdog
======================
Система мониторинга потоков, freeze detection и crash analysis.
"""

import sys
import threading
import time
import faulthandler
import signal
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict
import traceback


class ServiceHeartbeat:
    """Отслеживание сердцебиения сервисов"""

    def __init__(self):
        self.heartbeats: Dict[str, float] = {}
        self.lock = threading.Lock()

    def update(self, service_name: str) -> None:
        """Обновить время последнего сердцебиения сервиса"""
        with self.lock:
            self.heartbeats[service_name] = time.time()

    def get_last_heartbeat(self, service_name: str) -> Optional[float]:
        """Получить время последнего сердцебиения"""
        with self.lock:
            return self.heartbeats.get(service_name)

    def get_all_services(self) -> List[str]:
        """Получить список всех сервисов"""
        with self.lock:
            return list(self.heartbeats.keys())

    def check_service_health(self, service_name: str, timeout: float = 5.0) -> bool:
        """Проверить здоровье сервиса"""
        last_heartbeat = self.get_last_heartbeat(service_name)
        if last_heartbeat is None:
            return False
        return (time.time() - last_heartbeat) < timeout


class ThreadWatchdog:
    """Watchdog для мониторинга потоков и обнаружения зависаний"""

    def __init__(self, logger, check_interval: float = 1.0):
        self.logger = logger
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        self.services = ServiceHeartbeat()
        self.thread_states: Dict[str, float] = {}
        self.lock = threading.Lock()

    def start(self) -> None:
        """Запустить watchdog"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.thread.name = "ThreadWatchdog"
        self.thread.start()
        self.logger.log_thread("Watchdog started")

    def stop(self) -> None:
        """Остановить watchdog"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.logger.log_thread("Watchdog stopped")

    def register_service(self, service_name: str) -> None:
        """Зарегистрировать сервис для мониторинга"""
        with self.lock:
            self.services.update(service_name)
            self.thread_states[service_name] = time.time()

    def _watchdog_loop(self) -> None:
        """Основной цикл watchdog"""
        while self.running:
            try:
                self._check_threads()
                self._check_services()
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.log_exception(type(e), e, e.__traceback__)

    def _check_threads(self) -> None:
        """Проверить состояние потоков"""
        current_threads = threading.enumerate()
        current_time = time.time()

        # Проверить MainThread
        main_thread = next((t for t in current_threads if t.name == "MainThread"), None)
        if main_thread and main_thread.is_alive():
            last_state = self.thread_states.get("MainThread", current_time)
            if current_time - last_state > 3.0:
                self.logger.log_thread(
                    f"MainThread blocked for {current_time - last_state:.1f}s",
                    "warning"
                )

        # Обновить состояния
        with self.lock:
            for thread in current_threads:
                self.thread_states[thread.name] = current_time

    def _check_services(self) -> None:
        """Проверить здоровье сервисов"""
        services = self.services.get_all_services()
        for service_name in services:
            if not self.services.check_service_health(service_name):
                self.logger.log_system(
                    f"[SERVICE HANG] {service_name} not responding",
                    "error"
                )
                # Dump traceback при зависании сервиса
                faulthandler.dump_traceback()


class FreezeDetector:
    """Обнаружение freeze с детальной диагностикой"""

    def __init__(self, logger, timeout: float = 5.0):
        self.logger = logger
        self.timeout = timeout
        self.last_check = time.time()
        self.blocked_threads: Dict[str, float] = {}
        self.lock = threading.Lock()

    def start(self) -> None:
        """Запустить freeze detector"""
        self.logger.log_system("Freeze detector started")

    def check(self) -> bool:
        """Проверить на freeze"""
        current_time = time.time()
        elapsed = current_time - self.last_check

        if elapsed >= self.timeout:
            self.last_check = current_time
            return self._detect_freeze()

        return False

    def _detect_freeze(self) -> bool:
        """Обнаружить freeze"""
        current_threads = threading.enumerate()
        blocked_count = 0

        with self.lock:
            for thread in current_threads:
                if thread.name == "MainThread":
                    last_blocked = self.blocked_threads.get("MainThread", 0)
                    if current_time - last_blocked > 3.0:
                        blocked_count += 1

            if blocked_count > 0:
                self.logger.log_system(
                    f"[FREEZE DETECTED] {blocked_count} thread(s) blocked for >3s",
                    "critical"
                )
                faulthandler.dump_traceback()
                return True

        return False

    def mark_blocked(self, thread_name: str) -> None:
        """Отметить поток как заблокированный"""
        with self.lock:
            self.blocked_threads[thread_name] = time.time()


class GlobalExceptionHandler:
    """Глобальный обработчик исключений"""

    def __init__(self, logger):
        self.logger = logger
        self.original_excepthook = sys.excepthook
        self.original_thread_excepthook = threading.excepthook

    def install(self) -> None:
        """Установить глобальные обработчики"""
        sys.excepthook = self._handle_exception
        threading.excepthook = self._handle_thread_exception
        self.logger.log_system("Global exception handlers installed")

    def uninstall(self) -> None:
        """Снять глобальные обработчики"""
        sys.excepthook = self.original_excepthook
        threading.excepthook = self.original_thread_excepthook

    def _handle_exception(self, exc_type, exc_value, exc_traceback) -> None:
        """Обработчик исключений"""
        self.logger.log_exception(exc_type, exc_value, exc_traceback)
        self.original_excepthook(exc_type, exc_value, exc_traceback)

    def _handle_thread_exception(self, args) -> None:
        """Обработчик исключений в потоках"""
        self.logger.log_exception(
            args.exc_type,
            args.exc_value,
            args.exc_traceback
        )
        self.original_thread_excepthook(args)


class ImportProfiler:
    """Профайлер импортов с детальной статистикой"""

    def __init__(self, logger):
        self.logger = logger
        self.import_times: Dict[str, float] = {}
        self.lock = threading.Lock()

    def profile(self, module_name: str) -> None:
        """Профилировать импорт модуля"""
        start_time = time.time()
        try:
            __import__(module_name)
            duration = time.time() - start_time
            self.logger.log_import(module_name, duration)
        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"[IMPORT ERROR] {module_name} failed after {duration:.2f}s: {e}")


class StartupProfiler:
    """Профайлер запуска приложения"""

    def __init__(self, logger):
        self.logger = logger
        self.start_time = None
        self.events: List[tuple] = []

    def start(self) -> None:
        """Начать профилирование"""
        self.start_time = time.time()
        self.events = []
        self.logger.log_boot("Startup profiling started")

    def mark(self, event_name: str) -> None:
        """Отметить событие"""
        if self.start_time:
            elapsed = time.time() - self.start_time
            self.events.append((event_name, elapsed))
            self.logger.log_boot(f"{event_name} completed in {elapsed:.2f}s")

    def stop(self) -> None:
        """Завершить профилирование"""
        if self.start_time:
            total_time = time.time() - self.start_time
            self.logger.log_boot(f"Startup completed in {total_time:.2f}s")
            self.start_time = None


def setup_faulthandler(timeout: int = 5, repeat: bool = True) -> None:
    """Настроить faulthandler для dump traceback при freeze"""
    faulthandler.enable()
    faulthandler.dump_traceback_later(timeout=timeout, repeat=repeat)
    print(f"[SYSTEM] Faulthandler enabled (timeout: {timeout}s, repeat: {repeat})")


def setup_signal_handlers(logger) -> None:
    """Настроить обработчики сигналов"""
    def signal_handler(signum, frame):
        logger.log_system(f"Signal {signum} received, dumping traceback...", "warning")
        faulthandler.dump_traceback()
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.log_system("Signal handlers installed")