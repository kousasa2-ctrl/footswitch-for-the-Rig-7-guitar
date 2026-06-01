#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GR7 Hub - Main Application
===========================
Guitar Rig 7 Stage Control Hub - Launcher

Архитектура:
- main.py: bootstrap + lifecycle management
- ui/: GUI components
- services/: backend services
- api/: REST API
- vst3/: VST3 host
- midi/: MIDI routing
- webrtc/: WebRTC streaming
- core/: utilities (logger, config, state)
"""

import sys
import threading
import traceback

# Qt imports
from PyQt6.QtWidgets import QApplication, QMessageBox

# Application imports
from core.logger import Logger
from utils.qr_generator import QRGenerator
from ui.main_window import MainWindow, GR7Style


def setup_thread_exception_hook():
    """Setup exception handling in threads."""
    def excepthook(args):
        print(f"[THREAD ERROR] {args.thread}: {args.exc_type}: {args.exc_value}")
        if args.exc_traceback:
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = excepthook


def main():
    """
    Main application entry point.
    Bootstraps all services and starts the GUI.
    """
    # Setup exception hooks
    setup_thread_exception_hook()

    # Initialize Qt Application
    app = QApplication(sys.argv)

    # Initialize logger
    logger = Logger("GR7Hub")
    logger.info("=" * 60)
    logger.info("GR7 Hub - Guitar Rig 7 Stage Control System")
    logger.info("=" * 60)

    # Initialize QR generator
    QRGenerator.initialize(".qr_cache")
    logger.info("QR Generator initialized")

    # Apply theme
    try:
        GR7Style.apply_theme(app)
        app.setStyleSheet(GR7Style.get_stylesheet())
        logger.info("Theme applied successfully")
    except Exception as e:
        logger.error(f"Failed to apply theme: {e}")

    # Create and show main window
    try:
        window = MainWindow()
        window.show()
        logger.info("Main window created and shown")
    except Exception as e:
        logger.error(f"Failed to create main window: {e}")
        traceback.print_exc()
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("Ошибка запуска приложения")
        msg.setDetailedText(f"{e}\n\n{traceback.format_exc()}")
        msg.setWindowTitle("GR7 Hub Error")
        msg.exec()
        return 1

    # Run application
    logger.info("Starting event loop...")
    exit_code = app.exec()

    # Cleanup
    logger.info("Shutting down services...")
    try:
        if hasattr(window, 'closeEvent'):
            window.closeEvent(None)
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

    logger.info("GR7 Hub closed successfully")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
