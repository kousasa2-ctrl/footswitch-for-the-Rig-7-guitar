"""
Service Manager
===============
Centralized service lifecycle management with isolation, health monitoring,
and graceful degradation.
"""

import asyncio
import threading
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor

from .service_states import ServiceState, ServiceHealth, can_transition
from .logger import Logger


class IService(ABC):
    """Base interface for all services"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique service name"""
        pass
    
    @property
    @abstractmethod
    def dependencies(self) -> List[str]:
        """List of service names this service depends on"""
        pass
    
    @abstractmethod
    async def start(self) -> bool:
        """Start the service. Returns True if successful."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the service gracefully."""
        pass
    
    @abstractmethod
    async def healthcheck(self) -> ServiceHealth:
        """Check service health. Returns current health status."""
        pass
    
    @abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status for dashboard."""
        pass


@dataclass
class ServiceInfo:
    """Runtime information about a service"""
    service: IService
    state: ServiceState = ServiceState.STOPPED
    health: ServiceHealth = ServiceHealth.UNKNOWN
    error: Optional[str] = None
    start_time: Optional[float] = None
    last_healthcheck: Optional[float] = None
    restart_count: int = 0
    max_restarts: int = 3
    config_enabled: bool = True
    task: Optional[asyncio.Task] = None


class ServiceManager:
    """
    Manages service lifecycle with:
    - Dependency resolution
    - Isolated error handling
    - Health monitoring
    - Graceful degradation
    - Config-based enable/disable
    """
    
    def __init__(self, logger: Logger, config: Dict[str, bool]):
        self.logger = logger
        self.config = config
        self._services: Dict[str, ServiceInfo] = {}
        self._lock = threading.RLock()
        self._running = False
        self._health_check_interval = 5.0  # seconds
        self._health_check_task: Optional[asyncio.Task] = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ServiceMgr")
        self._state_change_callbacks: List[Callable[[str, ServiceState, ServiceState], None]] = []
        
    def register(self, service: IService) -> None:
        """Register a service with the manager"""
        with self._lock:
            if service.name in self._services:
                self.logger.log_service(service.name, "Service already registered, replacing", "warning")
            
            config_enabled = self.config.get(service.name, True)
            self._services[service.name] = ServiceInfo(
                service=service,
                state=ServiceState.DISABLED if not config_enabled else ServiceState.STOPPED,
                config_enabled=config_enabled
            )
            self.logger.log_service(service.name, f"Registered (enabled={config_enabled})", "info")
    
    def register_state_change_callback(self, callback: Callable[[str, ServiceState, ServiceState], None]) -> None:
        """Register callback for state changes"""
        self._state_change_callbacks.append(callback)
    
    def _notify_state_change(self, name: str, old_state: ServiceState, new_state: ServiceState) -> None:
        """Notify all callbacks of state change"""
        for callback in self._state_change_callbacks:
            try:
                callback(name, old_state, new_state)
            except Exception as e:
                self.logger.log_service(name, f"State change callback error: {e}", "error")
    
    def _set_state(self, name: str, new_state: ServiceState) -> bool:
        """Set service state with validation"""
        with self._lock:
            info = self._services.get(name)
            if not info:
                return False
            
            old_state = info.state
            if not can_transition(old_state, new_state):
                self.logger.log_service(name, f"Invalid state transition: {old_state.value} -> {new_state.value}", "error")
                return False
            
            info.state = new_state
            self._notify_state_change(name, old_state, new_state)
            return True
    
    async def start_service(self, name: str, timeout: float = 30.0) -> bool:
        """Start a single service with timeout and error isolation"""
        with self._lock:
            info = self._services.get(name)
            if not info:
                self.logger.log_service(name, "Service not found", "error")
                return False
            
            if not info.config_enabled:
                self.logger.log_service(name, "Service disabled in config", "warning")
                self._set_state(name, ServiceState.DISABLED)
                return False
            
            if info.state in (ServiceState.RUNNING, ServiceState.STARTING, ServiceState.DEGRADED):
                self.logger.log_service(name, f"Already running ({info.state.value})", "info")
                return True
            
            # Check dependencies
            for dep_name in info.service.dependencies:
                dep_info = self._services.get(dep_name)
                if not dep_info or dep_info.state != ServiceState.RUNNING:
                    self.logger.log_service(name, f"Dependency not running: {dep_name}", "error")
                    self._set_state(name, ServiceState.FAILED)
                    info.error = f"Dependency failed: {dep_name}"
                    return False
        
        # Start the service
        self._set_state(name, ServiceState.STARTING)
        info.start_time = time.time()
        info.error = None
        
        try:
            # Run with timeout
            success = await asyncio.wait_for(info.service.start(), timeout=timeout)
            
            if success:
                self._set_state(name, ServiceState.RUNNING)
                info.restart_count = 0
                self.logger.log_service(name, "Started successfully", "success")
            else:
                self._set_state(name, ServiceState.FAILED)
                info.error = "Service start returned False"
                self.logger.log_service(name, "Start returned False", "error")
            
            return success
            
        except asyncio.TimeoutError:
            self._set_state(name, ServiceState.FAILED)
            info.error = f"Start timeout after {timeout}s"
            self.logger.log_service(name, f"Start timeout after {timeout}s", "error")
            return False
            
        except Exception as e:
            self._set_state(name, ServiceState.FAILED)
            info.error = f"{type(e).__name__}: {e}"
            self.logger.log_service(name, f"Start failed: {e}", "error")
            self.logger.log_service(name, traceback.format_exc(), "error")
            return False
    
    async def stop_service(self, name: str, timeout: float = 10.0) -> bool:
        """Stop a single service gracefully"""
        with self._lock:
            info = self._services.get(name)
            if not info:
                return False
            
            if info.state in (ServiceState.STOPPED, ServiceState.DISABLED, ServiceState.STOPPING):
                return True
        
        self._set_state(name, ServiceState.STOPPING)
        
        try:
            await asyncio.wait_for(info.service.stop(), timeout=timeout)
            self._set_state(name, ServiceState.STOPPED)
            self.logger.log_service(name, "Stopped gracefully", "info")
            return True
            
        except asyncio.TimeoutError:
            self._set_state(name, ServiceState.FAILED)
            info.error = f"Stop timeout after {timeout}s"
            self.logger.log_service(name, f"Stop timeout after {timeout}s", "error")
            return False
            
        except Exception as e:
            self._set_state(name, ServiceState.FAILED)
            info.error = f"{type(e).__name__}: {e}"
            self.logger.log_service(name, f"Stop failed: {e}", "error")
            return False
    
    async def restart_service(self, name: str) -> bool:
        """Restart a service"""
        self.logger.log_service(name, "Restarting...", "info")
        await self.stop_service(name)
        await asyncio.sleep(0.5)  # Brief pause
        return await self.start_service(name)
    
    async def start_all(self) -> Dict[str, bool]:
        """Start all enabled services in dependency order"""
        self._running = True
        results = {}
        
        # Build dependency graph and sort topologically
        start_order = self._topological_sort()
        
        for name in start_order:
            info = self._services[name]
            if not info.config_enabled:
                self.logger.log_service(name, "Skipped (disabled in config)", "warning")
                results[name] = False
                continue
            
            self.logger.log_service(name, "Starting...", "info")
            results[name] = await self.start_service(name)
            
            # If a critical service fails, we could stop here
            # For now, continue starting other services
        
        # Start health monitoring
        self._start_health_monitoring()
        
        return results
    
    async def stop_all(self) -> None:
        """Stop all services in reverse dependency order"""
        self._running = False
        self._stop_health_monitoring()
        
        # Stop in reverse order
        stop_order = list(reversed(self._topological_sort()))
        
        for name in stop_order:
            info = self._services.get(name)
            if info and info.state not in (ServiceState.STOPPED, ServiceState.DISABLED):
                await self.stop_service(name)
    
    def _topological_sort(self) -> List[str]:
        """Sort services by dependencies (topological sort)"""
        visited = set()
        temp = set()
        order = []
        
        def visit(name: str):
            if name in temp:
                # Circular dependency - log but continue
                self.logger.log_service(name, "Circular dependency detected", "warning")
                return
            if name in visited:
                return
            
            temp.add(name)
            info = self._services.get(name)
            if info:
                for dep in info.service.dependencies:
                    if dep in self._services:
                        visit(dep)
            temp.remove(name)
            visited.add(name)
            order.append(name)
        
        for name in self._services:
            visit(name)
        
        return order
    
    def _start_health_monitoring(self) -> None:
        """Start background health monitoring"""
        if self._health_check_task and not self._health_check_task.done():
            return
        
        async def health_loop():
            while self._running:
                await asyncio.sleep(self._health_check_interval)
                if not self._running:
                    break
                await self._check_all_health()
        
        self._health_check_task = asyncio.create_task(health_loop())
        self.logger.log_service("ServiceManager", "Health monitoring started", "info")
    
    def _stop_health_monitoring(self) -> None:
        """Stop background health monitoring"""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                asyncio.get_event_loop().run_until_complete(
                    asyncio.wait_for(self._health_check_task, timeout=2.0)
                )
            except Exception:
                pass
            self._health_check_task = None
    
    async def _check_all_health(self) -> None:
        """Check health of all running services"""
        for name, info in self._services.items():
            if info.state not in (ServiceState.RUNNING, ServiceState.DEGRADED):
                continue
            
            try:
                health = await asyncio.wait_for(info.service.healthcheck(), timeout=5.0)
                info.health = health
                info.last_healthcheck = time.time()
                
                # Update state based on health
                if health == ServiceHealth.UNHEALTHY:
                    if info.state == ServiceState.RUNNING:
                        self._set_state(name, ServiceState.DEGRADED)
                        self.logger.log_service(name, "Health degraded", "warning")
                elif health == ServiceHealth.HEALTHY:
                    if info.state == ServiceState.DEGRADED:
                        self._set_state(name, ServiceState.RUNNING)
                        self.logger.log_service(name, "Health recovered", "success")
                        
            except asyncio.TimeoutError:
                info.health = ServiceHealth.UNHEALTHY
                self.logger.log_service(name, "Health check timeout", "warning")
            except Exception as e:
                info.health = ServiceHealth.UNHEALTHY
                self.logger.log_service(name, f"Health check error: {e}", "error")
    
    def get_service_status(self, name: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific service"""
        with self._lock:
            info = self._services.get(name)
            if not info:
                return None
            
            return {
                'name': name,
                'state': info.state.value,
                'health': info.health.value,
                'error': info.error,
                'uptime': time.time() - info.start_time if info.start_time else 0,
                'restart_count': info.restart_count,
                'enabled': info.config_enabled,
            }
    
    def get_all_status(self) -> Dict[str, Any]:
        """Get status of all services"""
        with self._lock:
            return {
                name: {
                    'state': info.state.value,
                    'health': info.health.value,
                    'error': info.error,
                    'uptime': time.time() - info.start_time if info.start_time else 0,
                    'restart_count': info.restart_count,
                    'enabled': info.config_enabled,
                }
                for name, info in self._services.items()
            }
    
    async def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed status including service-specific data"""
        result = {}
        for name, info in self._services.items():
            base = self.get_service_status(name)
            if base and info.state in (ServiceState.RUNNING, ServiceState.DEGRADED):
                try:
                    base['details'] = await asyncio.wait_for(
                        info.service.get_status(), timeout=3.0
                    )
                except Exception as e:
                    base['details'] = {'error': str(e)}
            result[name] = base
        return result
    
    def is_running(self, name: str) -> bool:
        """Check if a service is running"""
        with self._lock:
            info = self._services.get(name)
            return info and info.state in (ServiceState.RUNNING, ServiceState.DEGRADED)
    
    def enable_service(self, name: str) -> bool:
        """Enable a service at runtime"""
        with self._lock:
            info = self._services.get(name)
            if not info:
                return False
            info.config_enabled = True
            if info.state == ServiceState.DISABLED:
                self._set_state(name, ServiceState.STOPPED)
            return True
    
    def disable_service(self, name: str) -> bool:
        """Disable a service at runtime"""
        with self._lock:
            info = self._services.get(name)
            if not info:
                return False
            info.config_enabled = False
            if info.state not in (ServiceState.DISABLED, ServiceState.STOPPED):
                # Schedule stop
                asyncio.create_task(self.stop_service(name))
            self._set_state(name, ServiceState.DISABLED)
            return True
    
    def shutdown(self) -> None:
        """Shutdown the service manager"""
        self._running = False
        self._stop_health_monitoring()
        self._executor.shutdown(wait=True)
        self.logger.log_service("ServiceManager", "Shutdown complete", "info")