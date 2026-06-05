"""
Bootstrap System
================
Safe, async bootstrap with timeout, isolated error handling,
health states, and degraded mode support.
"""

import asyncio
import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Awaitable
from enum import Enum

from .logger import Logger
from .service_manager import ServiceManager, IService
from .service_states import ServiceState, ServiceHealth


class BootstrapPhase(Enum):
    """Bootstrap phases"""
    PRE_INIT = "pre_init"           # Before any services
    CORE_SERVICES = "core_services" # Core services (audio, config)
    EXTENDED_SERVICES = "extended_services"  # Extended services (firebase, webrtc, ble)
    UI_READY = "ui_ready"           # UI can be shown
    POST_INIT = "post_init"         # After UI is shown
    COMPLETE = "complete"           # All done


@dataclass
class BootstrapResult:
    """Result of bootstrap process"""
    success: bool
    phase: BootstrapPhase
    started_services: List[str] = field(default_factory=list)
    failed_services: List[str] = field(default_factory=list)
    disabled_services: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    duration: float = 0.0


@dataclass
class ServiceBootstrapConfig:
    """Configuration for a single service bootstrap"""
    name: str
    factory: Callable[[], IService]  # Factory to create service instance
    dependencies: List[str] = field(default_factory=list)
    timeout: float = 30.0
    critical: bool = False  # If critical and fails, bootstrap fails
    phase: BootstrapPhase = BootstrapPhase.EXTENDED_SERVICES
    healthcheck_interval: float = 5.0


class BootstrapManager:
    """
    Manages the complete application bootstrap process:
    - Loads service configuration
    - Creates ServiceManager
    - Registers and starts services in phases
    - Handles timeouts and errors per-service
    - Supports degraded mode
    - Reports detailed results
    """
    
    def __init__(self, logger: Logger, config_path: str = "config/services.json"):
        self.logger = logger
        self.config_path = Path(config_path)
        self.service_configs: List[ServiceBootstrapConfig] = []
        self.service_manager: Optional[ServiceManager] = None
        self._bootstrap_start_time: Optional[float] = None
        self._phase_callbacks: Dict[BootstrapPhase, List[Callable]] = {
            phase: [] for phase in BootstrapPhase
        }
        
    def load_service_config(self) -> Dict[str, bool]:
        """Load service enable/disable configuration"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.logger.log_boot(f"Loaded service config from {self.config_path}")
                return config
            else:
                self.logger.log_boot(f"Config not found: {self.config_path}, using defaults", "warning")
                return self._default_config()
        except Exception as e:
            self.logger.log_boot(f"Failed to load service config: {e}", "error")
            return self._default_config()
    
    def _default_config(self) -> Dict[str, bool]:
        """Default service configuration"""
        return {
            "audio": True,
            "firebase": False,
            "webrtc": False,
            "ble": False,
            "api_server": True,
            "qr": True,
            "midi": False,
            "preset_scan": True,
            "player": True,
            "vst3": True,
        }
    
    def register_service_config(self, config: ServiceBootstrapConfig) -> None:
        """Register a service for bootstrap"""
        self.service_configs.append(config)
        self.logger.log_boot(f"Registered service for bootstrap: {config.name} (phase: {config.phase.value})")
    
    def register_phase_callback(self, phase: BootstrapPhase, callback: Callable) -> None:
        """Register callback for a bootstrap phase"""
        self._phase_callbacks[phase].append(callback)
    
    async def run_bootstrap(self, service_manager: ServiceManager) -> BootstrapResult:
        """
        Run the complete bootstrap process.
        Returns BootstrapResult with detailed status.
        """
        self._bootstrap_start_time = time.time()
        self.service_manager = service_manager
        
        result = BootstrapResult(
            success=False,
            phase=BootstrapPhase.PRE_INIT
        )
        
        try:
            # Load config
            service_config = self.load_service_config()
            
            # Phase: PRE_INIT
            result.phase = BootstrapPhase.PRE_INIT
            await self._run_phase(BootstrapPhase.PRE_INIT)
            
            # Register all services
            for svc_config in self.service_configs:
                if not service_config.get(svc_config.name, True):
                    result.disabled_services.append(svc_config.name)
                    self.logger.log_boot(f"Service disabled in config: {svc_config.name}")
                    continue
                
                try:
                    service = svc_config.factory()
                    service_manager.register(service)
                except Exception as e:
                    self.logger.log_boot(f"Failed to create service {svc_config.name}: {e}", "error")
                    result.errors[svc_config.name] = str(e)
                    result.failed_services.append(svc_config.name)
            
            # Phase: CORE_SERVICES
            result.phase = BootstrapPhase.CORE_SERVICES
            await self._run_phase(BootstrapPhase.CORE_SERVICES)
            await self._start_services_in_phase(BootstrapPhase.CORE_SERVICES, result)
            
            # Phase: EXTENDED_SERVICES
            result.phase = BootstrapPhase.EXTENDED_SERVICES
            await self._run_phase(BootstrapPhase.EXTENDED_SERVICES)
            await self._start_services_in_phase(BootstrapPhase.EXTENDED_SERVICES, result)
            
            # Phase: UI_READY
            result.phase = BootstrapPhase.UI_READY
            await self._run_phase(BootstrapPhase.UI_READY)
            
            # Phase: POST_INIT
            result.phase = BootstrapPhase.POST_INIT
            await self._run_phase(BootstrapPhase.POST_INIT)
            
            # Check critical services
            critical_failed = any(
                svc in result.failed_services 
                for svc in self._get_critical_services()
            )
            
            result.success = not critical_failed
            result.phase = BootstrapPhase.COMPLETE
            
        except Exception as e:
            self.logger.log_boot(f"Bootstrap failed with exception: {e}", "error")
            self.logger.log_boot(traceback.format_exc(), "error")
            result.success = False
            result.errors["bootstrap"] = str(e)
        
        finally:
            result.duration = time.time() - self._bootstrap_start_time
            self.logger.log_boot(f"Bootstrap completed in {result.duration:.2f}s (success={result.success})")
            self.logger.log_boot(f"  Started: {result.started_services}")
            self.logger.log_boot(f"  Failed: {result.failed_services}")
            self.logger.log_boot(f"  Disabled: {result.disabled_services}")
        
        return result
    
    async def _run_phase(self, phase: BootstrapPhase) -> None:
        """Run all callbacks for a phase"""
        for callback in self._phase_callbacks.get(phase, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                self.logger.log_boot(f"Phase {phase.value} callback error: {e}", "error")
    
    async def _start_services_in_phase(self, phase: BootstrapPhase, result: BootstrapResult) -> None:
        """Start all services registered for a specific phase"""
        phase_services = [c for c in self.service_configs if c.phase == phase]
        
        for svc_config in phase_services:
            if svc_config.name in result.disabled_services:
                continue
            
            if svc_config.name in result.failed_services:
                continue
            
            self.logger.log_boot(f"Starting service: {svc_config.name}")
            
            try:
                success = await asyncio.wait_for(
                    service_manager.start_service(svc_config.name, timeout=svc_config.timeout),
                    timeout=svc_config.timeout + 2.0
                )
                
                if success:
                    result.started_services.append(svc_config.name)
                    self.logger.log_boot(f"Service started: {svc_config.name}", "success")
                else:
                    result.failed_services.append(svc_config.name)
                    error = service_manager.get_service_status(svc_config.name).get('error', 'Unknown error')
                    result.errors[svc_config.name] = error
                    self.logger.log_boot(f"Service failed: {svc_config.name} - {error}", "error")
                    
                    if svc_config.critical:
                        self.logger.log_boot(f"CRITICAL service failed: {svc_config.name}", "critical")
                        raise RuntimeError(f"Critical service failed: {svc_config.name}")
                        
            except asyncio.TimeoutError:
                result.failed_services.append(svc_config.name)
                result.errors[svc_config.name] = f"Timeout after {svc_config.timeout}s"
                self.logger.log_boot(f"Service timeout: {svc_config.name}", "error")
                
                if svc_config.critical:
                    raise RuntimeError(f"Critical service timeout: {svc_config.name}")
                    
            except Exception as e:
                result.failed_services.append(svc_config.name)
                result.errors[svc_config.name] = str(e)
                self.logger.log_boot(f"Service error: {svc_config.name} - {e}", "error")
                
                if svc_config.critical:
                    raise
    
    def _get_critical_services(self) -> List[str]:
        """Get list of critical service names"""
        return [c.name for c in self.service_configs if c.critical]


async def create_bootstrap_manager(logger: Logger) -> BootstrapManager:
    """Factory function to create and configure BootstrapManager"""
    bootstrap = BootstrapManager(logger)
    
    # Register phase callbacks
    bootstrap.register_phase_callback(BootstrapPhase.PRE_INIT, lambda: logger.log_boot("Phase: PRE_INIT"))
    bootstrap.register_phase_callback(BootstrapPhase.CORE_SERVICES, lambda: logger.log_boot("Phase: CORE_SERVICES"))
    bootstrap.register_phase_callback(BootstrapPhase.EXTENDED_SERVICES, lambda: logger.log_boot("Phase: EXTENDED_SERVICES"))
    bootstrap.register_phase_callback(BootstrapPhase.UI_READY, lambda: logger.log_boot("Phase: UI_READY"))
    bootstrap.register_phase_callback(BootstrapPhase.POST_INIT, lambda: logger.log_boot("Phase: POST_INIT"))
    
    return bootstrap