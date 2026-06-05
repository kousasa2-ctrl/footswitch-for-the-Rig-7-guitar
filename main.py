#!/usr/bin/env python3
"""
GR7 Hub - Main Entry Point
==========================
Production-grade modular async architecture.
Main thread = GUI ONLY. All heavy work in background.
"""

import sys
import os
import asyncio
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# ============================================================
# STEP 1: Logger init (FIRST - before anything else)
# ============================================================
from core.logger import Logger

logger = Logger()
logger.log_boot("=" * 60)
logger.log_boot("GR7 Hub Starting...")
logger.log_boot("=" * 60)

# ============================================================
# STEP 2: QApplication init
# ============================================================
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer

# Enable high DPI scaling
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)

app = QApplication(sys.argv)
app.setApplicationName("GR7 Hub")
app.setApplicationVersion("2.0.0")
app.setOrganizationName("GR7 Hub")

# ============================================================
# STEP 3: Show empty UI INSTANTLY
# ============================================================
from ui.main_window import MainWindow

# Create and show main window immediately
main_window = MainWindow(logger)
main_window.show()

logger.log_boot("UI shown - starting background bootstrap...")

# ============================================================
# STEP 4: Background bootstrap
# ============================================================
async def run_bootstrap():
    """Run background bootstrap after UI is shown"""
    try:
        # Import bootstrap components
        from core.config_loader import ConfigLoader
        from core.service_manager import ServiceManager
        from core.bootstrap import BootstrapManager, BootstrapPhase, ServiceBootstrapConfig
        from services import SERVICE_FACTORIES, SERVICE_DEPENDENCIES
        
        # Load service config
        config_loader = ConfigLoader()
        service_config = config_loader.load_services_config()
        
        # Create service manager
        service_manager = ServiceManager(logger, service_config)
        
        # Create bootstrap manager
        bootstrap = BootstrapManager(logger)
        
        # Register services with their factories
        for name, factory in SERVICE_FACTORIES.items():
            if service_config.get(name, True):  # Only register if enabled
                deps = SERVICE_DEPENDENCIES.get(name, [])
                phase = BootstrapPhase.CORE_SERVICES if name in ('audio', 'player') else BootstrapPhase.EXTENDED_SERVICES
                critical = name in ('audio',)  # Audio is critical
                
                bootstrap.register_service_config(ServiceBootstrapConfig(
                    name=name,
                    factory=lambda f=factory: f(config_loader, logger),
                    dependencies=deps,
                    timeout=30.0,
                    critical=critical,
                    phase=phase,
                ))
        
        # Register phase callbacks for UI updates
        def on_phase(phase_name):
            logger.log_boot(f"Bootstrap phase: {phase_name}")
            # Update UI with phase
            if hasattr(main_window, 'update_bootstrap_phase'):
                main_window.update_bootstrap_phase(phase_name)
        
        for phase in BootstrapPhase:
            bootstrap.register_phase_callback(phase, lambda p=phase: on_phase(p.value))
        
        # Run bootstrap
        result = await bootstrap.run_bootstrap(service_manager)
        
        # Store service manager in main window
        main_window.set_service_manager(service_manager)
        
        # Update UI with results
        if hasattr(main_window, 'on_bootstrap_complete'):
            main_window.on_bootstrap_complete(result)
        
        logger.log_boot(f"Bootstrap completed: {result.success}", "success" if result.success else "error")
        logger.log_boot(f"  Started: {result.started_services}")
        logger.log_boot(f"  Failed: {result.failed_services}")
        logger.log_boot(f"  Disabled: {result.disabled_services}")
        
        # Start service health monitoring UI updates
        if hasattr(main_window, 'start_health_monitoring'):
            main_window.start_health_monitoring(service_manager)
        
        return service_manager
        
    except Exception as e:
        logger.log_boot(f"Bootstrap failed: {e}", "error")
        logger.log_boot(traceback.format_exc(), "error")
        if hasattr(main_window, 'on_bootstrap_error'):
            main_window.on_bootstrap_error(str(e))
        return None


def start_background_bootstrap():
    """Start bootstrap in asyncio event loop"""
    # Create new event loop for background tasks
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Run bootstrap
    service_manager = loop.run_until_complete(run_bootstrap())
    
    # Keep loop running for health monitoring
    if service_manager:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(service_manager.stop_all())
            loop.close()


# Start bootstrap in background thread
import threading
bootstrap_thread = threading.Thread(
    target=start_background_bootstrap,
    daemon=True,
    name="BootstrapThread"
)
bootstrap_thread.start()

# ============================================================
# Run Qt event loop (MAIN THREAD)
# ============================================================
logger.log_boot("Entering Qt main loop")

try:
    exit_code = app.exec()
    logger.log_boot(f"Application exiting with code {exit_code}", "info")
    sys.exit(exit_code)
except KeyboardInterrupt:
    logger.log_boot("Keyboard interrupt", "warning")
    sys.exit(0)
except Exception as e:
    logger.log_boot(f"Fatal error: {e}", "critical")
    logger.log_boot(traceback.format_exc(), "critical")
    sys.exit(1)