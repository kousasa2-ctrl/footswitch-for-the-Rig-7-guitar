#!/usr/bin/env python3
"""
GR7 Hub - Main Window
=====================
Modern UI with service dashboard, realtime audio monitoring,
and modular service integration.
"""

import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QFrame, QProgressBar, QTextEdit,
    QGroupBox, QGridLayout, QComboBox, QSlider, QListWidget, QListWidgetItem,
    QSplitter, QPlainTextEdit, QCheckBox, QLineEdit, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QColor, QPalette, QTextCursor, QFont, QPixmap

from core import Logger, ServiceManager, ServiceState, ServiceHealth
from services import SERVICE_FACTORIES, SERVICE_DEPENDENCIES


class GUISignals(QObject):
    """Thread-safe signals for GUI updates"""
    log_signal = pyqtSignal(str, str)
    service_status_signal = pyqtSignal(str, dict)
    bootstrap_phase_signal = pyqtSignal(str)
    bootstrap_complete_signal = pyqtSignal(dict)
    bootstrap_error_signal = pyqtSignal(str)
    vu_meter_signal = pyqtSignal(dict)
    waveform_signal = pyqtSignal(dict)


class GR7Style:
    """Стили в стиле Guitar Rig 7"""

    @staticmethod
    def apply_theme(app):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#1A1A1A"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#E0E0E0"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#121212"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1E1E1E"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1A1A1A"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#E0E0E0"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#E0E0E0"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#2A2A2A"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#E0E0E0"))
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#FF9D00"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#FF9D00"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        app.setPalette(palette)

    @staticmethod
    def get_stylesheet():
        return """
            QMainWindow {
                background-color: #1A1A1A;
            }

            QTabWidget::pane {
                border: 1px solid #2D2D2D;
                background-color: #151515;
                top: -1px;
            }

            QTabBar::tab {
                background-color: #222222;
                color: #888888;
                border: 1px solid #2D2D2D;
                padding: 8px 16px;
                margin-right: 2px;
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
            }

            QTabBar::tab:selected {
                background-color: #151515;
                color: #FF9D00;
                border-bottom: 1px solid #151515;
            }

            QTabBar::tab:hover:!selected {
                background-color: #2B2B2B;
                color: #CCCCCC;
            }

            QPushButton {
                background-color: #2A2A2A;
                color: #E0E0E0;
                border: 1px solid #3D3D3D;
                padding: 6px 12px;
                border-radius: 2px;
                min-height: 18px;
                font-size: 11px;
            }

            QPushButton:hover {
                background-color: #353535;
                border: 1px solid #4D4D4D;
            }

            QPushButton:pressed {
                background-color: #1A1A1A;
                color: #FF9D00;
            }

            QPushButton:disabled {
                background-color: #1A1A1A;
                color: #555555;
                border: 1px solid #252525;
            }

            QPushButton#accent-btn {
                background-color: #3A2A15;
                border: 1px solid #FF9D00;
                color: #FF9D00;
            }

            QPushButton#accent-btn:hover {
                background-color: #4A351B;
            }

            QGroupBox {
                border: 1px solid #2D2D2D;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
                color: #888888;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                left: 10px;
            }

            QTextEdit, QPlainTextEdit {
                background-color: #0F0F0F;
                border: 1px solid #252525;
                color: #A0A0A0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }

            QListWidget {
                background-color: #121212;
                border: 1px solid #252525;
            }

            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #1A1A1A;
            }

            QListWidget::item:hover {
                background-color: #1A1A1A;
            }

            QListWidget::item:selected {
                background-color: #2D251A;
                color: #FF9D00;
            }

            QComboBox, QSpinBox {
                background-color: #222222;
                border: 1px solid #3D3D3D;
                padding: 4px;
                color: #E0E0E0;
            }

            QComboBox::drop-down {
                border: none;
                background-color: #2A2A2A;
            }

            QSlider::groove:horizontal {
                border: 1px solid #262626;
                height: 4px;
                background: #121212;
            }

            QSlider::handle:horizontal {
                background: #444444;
                border: 1px solid #555555;
                width: 12px;
                margin: -5px 0;
                border-radius: 2px;
            }

            QSlider::handle:horizontal:hover {
                background: #FF9D00;
                border: 1px solid #FFAA22;
            }

            QProgressBar {
                border: 1px solid #2D2D2D;
                border-radius: 2px;
                background-color: #121212;
                text-align: center;
                color: #E0E0E0;
            }

            QProgressBar::chunk {
                background-color: #FF9D00;
                border-radius: 1px;
            }
        """


class ServiceDashboardTab(QWidget):
    """Service dashboard showing all service statuses"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.service_widgets = {}
        self.init_ui()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.setInterval(1000)
        self.update_timer.timeout.connect(self.update_all_services)
        self.update_timer.start()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("SERVICE DASHBOARD")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #FF9D00;")
        header.addWidget(title)
        header.addStretch()
        
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.update_all_services)
        header.addWidget(self.btn_refresh)
        
        layout.addLayout(header)
        
        # Scroll area for services
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.services_container = QWidget()
        self.services_layout = QVBoxLayout(self.services_container)
        self.services_layout.setContentsMargins(0, 0, 0, 0)
        self.services_layout.setSpacing(10)
        
        scroll.setWidget(self.services_container)
        layout.addWidget(scroll)
        
        # Create service widgets
        self.create_service_widgets()
    
    def create_service_widgets(self):
        """Create widgets for each service"""
        services = [
            ('audio', 'Audio Engine', '🎵'),
            ('player', 'Backing Track Player', '🎧'),
            ('firebase', 'Firebase', '☁️'),
            ('qr', 'QR Generator', '📱'),
            ('ble', 'Bluetooth LE', '📶'),
            ('webrtc', 'WebRTC', '🌐'),
            ('preset_scan', 'Preset Catalog', '📚'),
            ('api_server', 'API Server', '🔌'),
        ]
        
        for name, display_name, icon in services:
            widget = self.create_service_widget(name, display_name, icon)
            self.service_widgets[name] = widget
            self.services_layout.addWidget(widget)
        
        self.services_layout.addStretch()
    
    def create_service_widget(self, name: str, display_name: str, icon: str) -> QGroupBox:
        """Create a service status widget"""
        group = QGroupBox(f"{icon} {display_name}")
        group.setObjectName(f"service_{name}")
        layout = QGridLayout(group)
        
        # Status indicator
        status_label = QLabel("●")
        status_label.setObjectName("status_indicator")
        status_label.setStyleSheet("font-size: 16px; color: #555555;")
        layout.addWidget(QLabel("Status:"), 0, 0)
        layout.addWidget(status_label, 0, 1)
        
        # State text
        state_label = QLabel("Unknown")
        state_label.setObjectName("state_label")
        state_label.setStyleSheet("color: #888888;")
        layout.addWidget(state_label, 0, 2)
        
        # Health
        health_label = QLabel("Health: Unknown")
        health_label.setObjectName("health_label")
        health_label.setStyleSheet("color: #888888;")
        layout.addWidget(health_label, 1, 0, 1, 3)
        
        # Details
        details_label = QLabel("")
        details_label.setObjectName("details_label")
        details_label.setStyleSheet("color: #666666; font-size: 10px;")
        details_label.setWordWrap(True)
        layout.addWidget(details_label, 2, 0, 1, 3)
        
        # Progress bar for loading
        progress = QProgressBar()
        progress.setObjectName("progress_bar")
        progress.setVisible(False)
        progress.setRange(0, 0)  # Indeterminate
        layout.addWidget(progress, 3, 0, 1, 3)
        
        # Store references
        group.status_label = status_label
        group.state_label = state_label
        group.health_label = health_label
        group.details_label = details_label
        group.progress = progress
        
        return group
    
    def update_service_widget(self, name: str, status: Dict[str, Any]):
        """Update a service widget with status"""
        widget = self.service_widgets.get(name)
        if not widget:
            return
        
        state = status.get('state', 'unknown')
        health = status.get('health', 'unknown')
        error = status.get('error')
        enabled = status.get('enabled', True)
        
        # Update state
        widget.state_label.setText(f"State: {state.upper()}")
        
        # Update status indicator color
        if state == 'running':
            widget.status_label.setStyleSheet("font-size: 16px; color: #33FF33;")
        elif state == 'degraded':
            widget.status_label.setStyleSheet("font-size: 16px; color: #FF9D00;")
        elif state == 'failed':
            widget.status_label.setStyleSheet("font-size: 16px; color: #FF3333;")
        elif state == 'disabled':
            widget.status_label.setStyleSheet("font-size: 16px; color: #555555;")
        elif state == 'starting':
            widget.status_label.setStyleSheet("font-size: 16px; color: #FF9D00;")
        else:
            widget.status_label.setStyleSheet("font-size: 16px; color: #555555;")
        
        # Update health
        if health == 'healthy':
            widget.health_label.setText("Health: ✓ Healthy")
            widget.health_label.setStyleSheet("color: #33FF33;")
        elif health == 'degraded':
            widget.health_label.setText("Health: ⚠ Degraded")
            widget.health_label.setStyleSheet("color: #FF9D00;")
        elif health == 'unhealthy':
            widget.health_label.setText("Health: ✗ Unhealthy")
            widget.health_label.setStyleSheet("color: #FF3333;")
        else:
            widget.health_label.setText("Health: ? Unknown")
            widget.health_label.setStyleSheet("color: #888888;")
        
        # Update details
        details = []
        if error:
            details.append(f"Error: {error}")
        if 'uptime' in status:
            uptime = status['uptime']
            if uptime > 0:
                details.append(f"Uptime: {uptime:.1f}s")
        if 'cpu_load' in status:
            details.append(f"CPU: {status['cpu_load']:.1f}%")
        if 'buffer_underruns' in status:
            details.append(f"Underruns: {status['buffer_underruns']}")
        
        widget.details_label.setText(" | ".join(details) if details else "No details")
        
        # Show/hide progress for starting state
        widget.progress.setVisible(state == 'starting')
    
    def update_all_services(self):
        """Update all service widgets"""
        if not self.main_window.service_manager:
            return
        
        try:
            statuses = self.main_window.service_manager.get_all_status()
            for name, status in statuses.items():
                self.update_service_widget(name, status)
        except Exception as e:
            self.main_window.log(f"Dashboard update error: {e}", "error")


class AudioMonitorTab(QWidget):
    """Real-time audio monitoring with VU meters and waveform"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.setInterval(50)  # 20 FPS
        self.update_timer.timeout.connect(self.update_audio)
        self.update_timer.start()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # VU Meters
        vu_group = QGroupBox("VU METERS")
        vu_layout = QHBoxLayout(vu_group)
        
        # Left channel
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("LEFT"))
        self.vu_left = QProgressBar()
        self.vu_left.setOrientation(Qt.Orientation.Vertical)
        self.vu_left.setRange(0, 100)
        self.vu_left.setFixedWidth(60)
        self.vu_left.setStyleSheet("""
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #33FF33, stop:0.7 #FF9D00, stop:1 #FF3333);
            }
        """)
        left_layout.addWidget(self.vu_left)
        self.vu_left_label = QLabel("-∞ dB")
        self.vu_left_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.vu_left_label)
        vu_layout.addLayout(left_layout)
        
        # Right channel
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("RIGHT"))
        self.vu_right = QProgressBar()
        self.vu_right.setOrientation(Qt.Orientation.Vertical)
        self.vu_right.setRange(0, 100)
        self.vu_right.setFixedWidth(60)
        self.vu_right.setStyleSheet("""
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #33FF33, stop:0.7 #FF9D00, stop:1 #FF3333);
            }
        """)
        right_layout.addWidget(self.vu_right)
        self.vu_right_label = QLabel("-∞ dB")
        self.vu_right_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.vu_right_label)
        vu_layout.addLayout(right_layout)
        
        # Peak indicators
        peak_layout = QVBoxLayout()
        peak_layout.addWidget(QLabel("PEAKS"))
        self.peak_left_label = QLabel("L: -∞ dB")
        self.peak_right_label = QLabel("R: -∞ dB")
        self.clip_label = QLabel("CLIP: No")
        self.clip_label.setStyleSheet("color: #33FF33; font-weight: bold;")
        peak_layout.addWidget(self.peak_left_label)
        peak_layout.addWidget(self.peak_right_label)
        peak_layout.addWidget(self.clip_label)
        vu_layout.addLayout(peak_layout)
        
        vu_layout.addStretch()
        layout.addWidget(vu_group)
        
        # Waveform
        wave_group = QGroupBox("WAVEFORM")
        wave_layout = QVBoxLayout(wave_group)
        
        self.waveform_canvas = QLabel()
        self.waveform_canvas.setMinimumHeight(150)
        self.waveform_canvas.setStyleSheet("background-color: #0F0F0F; border: 1px solid #252525;")
        self.waveform_canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wave_layout.addWidget(self.waveform_canvas)
        
        layout.addWidget(wave_group)
        
        # Audio info
        info_group = QGroupBox("AUDIO INFO")
        info_layout = QGridLayout(info_group)
        
        self.info_labels = {}
        info_items = [
            ('sample_rate', 'Sample Rate:', '0 Hz'),
            ('block_size', 'Block Size:', '0'),
            ('latency', 'Latency:', '0 ms'),
            ('cpu_load', 'CPU Load:', '0%'),
            ('underruns', 'Underruns:', '0'),
            ('overruns', 'Overruns:', '0'),
        ]
        
        for i, (key, label, default) in enumerate(info_items):
            info_layout.addWidget(QLabel(label), i // 3, (i % 3) * 2)
            value_label = QLabel(default)
            value_label.setStyleSheet("color: #FF9D00; font-weight: bold;")
            info_layout.addWidget(value_label, i // 3, (i % 3) * 2 + 1)
            self.info_labels[key] = value_label
        
        layout.addWidget(info_group)
        layout.addStretch()
    
    def update_audio(self):
        """Update audio monitoring from audio service"""
        if not self.main_window.service_manager:
            return
        
        try:
            if not self.main_window.service_manager.is_running('audio'):
                return
            
            # Get audio service status
            status = self.main_window.service_manager.get_service_status('audio')
            if not status:
                return
            
            details = status.get('details', {})
            engine = details.get('engine', {})
            vu = details.get('vu_meter', {})
            waveform = details.get('waveform', {})
            
            # Update VU meters
            left = vu.get('left', 0.0)
            right = vu.get('right', 0.0)
            peak_left = vu.get('peak_left', 0.0)
            peak_right = vu.get('peak_right', 0.0)
            clipping = vu.get('clipping', False)
            
            # Convert to dB and percentage
            def to_db(linear):
                if linear <= 0:
                    return -120
                return 20 * (linear).bit_length() - 20  # Approximate
            
            def to_percent(linear):
                return min(100, int(linear * 100))
            
            self.vu_left.setValue(to_percent(left))
            self.vu_right.setValue(to_percent(right))
            
            self.vu_left_label.setText(f"{to_db(left):.1f} dB")
            self.vu_right_label.setText(f"{to_db(right):.1f} dB")
            
            self.peak_left_label.setText(f"L: {to_db(peak_left):.1f} dB")
            self.peak_right_label.setText(f"R: {to_db(peak_right):.1f} dB")
            
            if clipping:
                self.clip_label.setText("CLIP: YES!")
                self.clip_label.setStyleSheet("color: #FF3333; font-weight: bold;")
            else:
                self.clip_label.setText("CLIP: No")
                self.clip_label.setStyleSheet("color: #33FF33; font-weight: bold;")
            
            # Update waveform
            if waveform.get('left') and waveform.get('right'):
                self.draw_waveform(waveform['left'], waveform['right'])
            
            # Update info
            self.info_labels['sample_rate'].setText(f"{engine.get('sample_rate', 0)} Hz")
            self.info_labels['block_size'].setText(str(engine.get('block_size', 0)))
            self.info_labels['latency'].setText(f"{engine.get('callback_time_ms', 0):.2f} ms")
            self.info_labels['cpu_load'].setText(f"{engine.get('cpu_load', 0):.1f}%")
            self.info_labels['underruns'].setText(str(engine.get('buffer_underruns', 0)))
            self.info_labels['overruns'].setText(str(engine.get('buffer_overruns', 0)))
            
        except Exception as e:
            self.main_window.log(f"Audio monitor error: {e}", "error")
    
    def draw_waveform(self, left_data, right_data):
        """Draw waveform on canvas"""
        # Simple text-based waveform for now
        # In production, use QPainter for actual waveform drawing
        width = 80
        left_str = ""
        right_str = ""
        
        for i in range(min(width, len(left_data))):
            val = abs(left_data[i]) if i < len(left_data) else 0
            bar = int(val * 10)
            left_str += "█" * min(bar, 5) + " " * (5 - min(bar, 5))
        
        for i in range(min(width, len(right_data))):
            val = abs(right_data[i]) if i < len(right_data) else 0
            bar = int(val * 10)
            right_str += "█" * min(bar, 5) + " " * (5 - min(bar, 5))
        
        self.waveform_canvas.setText(f"L: {left_str}\nR: {right_str}")
        self.waveform_canvas.setFont(QFont("Consolas", 8))


class PresetBrowserTab(QWidget):
    """Preset browser with search and categories"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - preset list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        search_box = QGroupBox("Search Presets")
        search_layout = QVBoxLayout(search_box)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search presets...")
        self.search_input.textChanged.connect(self.filter_presets)
        search_layout.addWidget(self.search_input)
        left_layout.addWidget(search_box)
        
        # Category filter
        cat_box = QGroupBox("Category")
        cat_layout = QVBoxLayout(cat_box)
        self.category_combo = QComboBox()
        self.category_combo.addItem("All Categories")
        self.category_combo.currentTextChanged.connect(self.filter_presets)
        cat_layout.addWidget(self.category_combo)
        left_layout.addWidget(cat_box)
        
        presets_box = QGroupBox("Presets")
        presets_layout = QVBoxLayout(presets_box)
        self.preset_list = QListWidget()
        self.preset_list.itemSelectionChanged.connect(self.on_preset_selected)
        presets_layout.addWidget(self.preset_list)
        left_layout.addWidget(presets_box)
        
        # Right panel - preset details
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        info_box = QGroupBox("Preset Info")
        info_layout = QGridLayout(info_box)
        info_layout.addWidget(QLabel("Name:"), 0, 0)
        self.lbl_name = QLabel("-")
        self.lbl_name.setStyleSheet("color: #FF9D00; font-weight: bold;")
        info_layout.addWidget(self.lbl_name, 0, 1)
        
        info_layout.addWidget(QLabel("Category:"), 1, 0)
        self.lbl_category = QLabel("-")
        info_layout.addWidget(self.lbl_category, 1, 1)
        
        info_layout.addWidget(QLabel("Components:"), 2, 0)
        self.lbl_components = QLabel("-")
        info_layout.addWidget(self.lbl_components, 2, 1)
        right_layout.addWidget(info_box)
        
        rack_box = QGroupBox("Rack Chain")
        rack_layout = QVBoxLayout(rack_box)
        self.rack_list = QListWidget()
        rack_layout.addWidget(self.rack_list)
        
        btn_layout = QHBoxLayout()
        self.btn_load = QPushButton("Load Preset")
        self.btn_load.setObjectName("accent-btn")
        self.btn_load.clicked.connect(self.on_load_clicked)
        btn_layout.addWidget(self.btn_load)
        rack_layout.addLayout(btn_layout)
        
        right_layout.addWidget(rack_box)
        
        # Favorites
        fav_box = QGroupBox("Favorites")
        fav_layout = QVBoxLayout(fav_box)
        self.fav_list = QListWidget()
        fav_layout.addWidget(self.fav_list)
        right_layout.addWidget(fav_box)
        
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([450, 750])
        
        layout.addWidget(splitter)
    
    def update_presets(self):
        """Update preset list from catalog service"""
        if not self.main_window.service_manager:
            return
        
        try:
            if not self.main_window.service_manager.is_running('preset_scan'):
                return
            
            status = self.main_window.service_manager.get_service_status('preset_scan')
            if not status:
                return
            
            details = status.get('details', {})
            categories = details.get('categories', {})
            
            # Update category combo
            current = self.category_combo.currentText()
            self.category_combo.clear()
            self.category_combo.addItem("All Categories")
            for cat in sorted(categories.keys()):
                self.category_combo.addItem(cat)
            if current in [self.category_combo.itemText(i) for i in range(self.category_combo.count())]:
                self.category_combo.setCurrentText(current)
            
            # Update preset list
            self.filter_presets()
            
        except Exception as e:
            self.main_window.log(f"Preset update error: {e}", "error")
    
    def filter_presets(self):
        """Filter preset list"""
        if not self.main_window.service_manager:
            return
        
        try:
            search = self.search_input.text().lower()
            category = self.category_combo.currentText()
            
            status = self.main_window.service_manager.get_service_status('preset_scan')
            if not status:
                return
            
            details = status.get('details', {})
            # Get presets from service
            # For now, just show placeholder
            self.preset_list.clear()
            self.preset_list.addItem("Preset loading from service...")
            
        except Exception as e:
            self.main_window.log(f"Filter presets error: {e}", "error")
    
    def on_preset_selected(self):
        selected = self.preset_list.selectedItems()
        if not selected:
            return
        # Update details
        self.lbl_name.setText(selected[0].text())
    
    def on_load_clicked(self):
        selected = self.preset_list.selectedItems()
        if not selected:
            return
        self.main_window.log(f"Load preset: {selected[0].text()}", "info")


class PlayerTab(QWidget):
    """Backing track player"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()
        
        self.update_timer = QTimer()
        self.update_timer.setInterval(500)
        self.update_timer.timeout.connect(self.update_player)
        self.update_timer.start()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Playlist
        left_box = QGroupBox("Playlist")
        left_layout = QVBoxLayout(left_box)
        self.track_list = QListWidget()
        self.track_list.itemDoubleClicked.connect(self.on_track_double_clicked)
        left_layout.addWidget(self.track_list)
        splitter.addWidget(left_box)
        
        # Controls
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        control_box = QGroupBox("Playback Control")
        control_layout = QVBoxLayout(control_box)
        
        self.lbl_current_track = QLabel("No track selected")
        self.lbl_current_track.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_current_track.setStyleSheet("font-size: 14px; font-weight: bold; color: #FF9D00; padding: 10px;")
        control_layout.addWidget(self.lbl_current_track)
        
        progress_layout = QHBoxLayout()
        self.lbl_time_cur = QLabel("00:00")
        self.slider_progress = QSlider(Qt.Orientation.Horizontal)
        self.slider_progress.sliderMoved.connect(self.on_slider_moved)
        self.lbl_time_total = QLabel("00:00")
        progress_layout.addWidget(self.lbl_time_cur)
        progress_layout.addWidget(self.slider_progress)
        progress_layout.addWidget(self.lbl_time_total)
        control_layout.addLayout(progress_layout)
        
        btn_layout = QHBoxLayout()
        self.btn_prev = QPushButton("⏮ Prev")
        self.btn_prev.clicked.connect(self.on_prev_clicked)
        self.btn_play = QPushButton("▶ PLAY")
        self.btn_play.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.btn_play.clicked.connect(self.on_play_clicked)
        self.btn_pause = QPushButton("⏸ PAUSE")
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_next = QPushButton("⏭ Next")
        self.btn_next.clicked.connect(self.on_next_clicked)
        
        btn_layout.addWidget(self.btn_prev)
        btn_layout.addWidget(self.btn_play)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_next)
        control_layout.addLayout(btn_layout)
        
        vol_layout = QHBoxLayout()
        vol_layout.addWidget(QLabel("Volume:"))
        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(80)
        self.slider_volume.valueChanged.connect(self.on_volume_changed)
        vol_layout.addWidget(self.slider_volume)
        control_layout.addLayout(vol_layout)
        
        right_layout.addWidget(control_box)
        
        # Waveform
        wave_box = QGroupBox("Waveform")
        wave_layout = QVBoxLayout(wave_box)
        self.waveform_label = QLabel()
        self.waveform_label.setMinimumHeight(100)
        self.waveform_label.setStyleSheet("background-color: #0F0F0F; border: 1px solid #252525;")
        self.waveform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.waveform_label.setFont(QFont("Consolas", 8))
        wave_layout.addWidget(self.waveform_label)
        right_layout.addWidget(wave_box)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([500, 700])
        layout.addWidget(splitter)
    
    def update_player(self):
        """Update player UI from service"""
        if not self.main_window.service_manager:
            return
        
        try:
            if not self.main_window.service_manager.is_running('player'):
                return
            
            status = self.main_window.service_manager.get_service_status('player')
            if not status:
                return
            
            details = status.get('details', {})
            current = details.get('current_track')
            state = details.get('state', 'stopped')
            position = details.get('position', 0)
            duration = details.get('duration', 0)
            volume = details.get('volume', 1.0)
            vu = details.get('vu_meter', {})
            
            # Update track info
            if current:
                self.lbl_current_track.setText(current.get('name', 'Unknown'))
            
            # Update progress
            if duration > 0:
                self.slider_progress.setRange(0, int(duration))
                self.slider_progress.setValue(int(position))
                self.lbl_time_cur.setText(self.format_time(position))
                self.lbl_time_total.setText(self.format_time(duration))
            
            # Update volume
            self.slider_volume.setValue(int(volume * 100))
            
            # Update waveform
            if current:
                track_id = current.get('id')
                if track_id:
                    waveform = self.main_window.service_manager.get_service_status('player')
                    # Would get waveform from service
                    pass
            
        except Exception as e:
            self.main_window.log(f"Player update error: {e}", "error")
    
    def format_time(self, seconds):
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{mins:02d}:{secs:02d}"
    
    def on_track_double_clicked(self, item):
        track_data = item.data(Qt.ItemDataRole.UserRole)
        if track_data:
            self.play_track(track_data.get('id'))
    
    def play_track(self, track_id):
        if not self.main_window.service_manager:
            return
        # Would call player service
        self.main_window.log(f"Play track: {track_id}", "info")
    
    def on_play_clicked(self):
        self.main_window.log("Play clicked", "info")
    
    def on_pause_clicked(self):
        self.main_window.log("Pause clicked", "info")
    
    def on_prev_clicked(self):
        self.main_window.log("Previous track", "info")
    
    def on_next_clicked(self):
        self.main_window.log("Next track", "info")
    
    def on_volume_changed(self, value):
        self.main_window.log(f"Volume: {value}%", "info")
    
    def on_slider_moved(self, value):
        self.main_window.log(f"Seek: {value}s", "info")


class SettingsTab(QWidget):
    """Settings tab"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        
        grid = QGridLayout()
        
        # Audio settings
        audio_box = QGroupBox("Audio Engine")
        audio_layout = QVBoxLayout(audio_box)
        
        audio_layout.addWidget(QLabel("Sample Rate:"))
        self.combo_sr = QComboBox()
        self.combo_sr.addItems(["44100", "48000", "88200", "96000"])
        self.combo_sr.setCurrentText("48000")
        audio_layout.addWidget(self.combo_sr)
        
        audio_layout.addWidget(QLabel("Block Size:"))
        self.combo_bs = QComboBox()
        self.combo_bs.addItems(["32", "64", "128", "256", "512"])
        self.combo_bs.setCurrentText("64")
        audio_layout.addWidget(self.combo_bs)
        
        audio_layout.addWidget(QLabel("ASIO Driver:"))
        self.combo_asio = QComboBox()
        self.combo_asio.addItems(["Auto", "ASIO4ALL v2", "FL Studio ASIO", "Focusrite USB ASIO"])
        audio_layout.addWidget(self.combo_asio)
        
        self.btn_restart_audio = QPushButton("Restart Audio Engine")
        self.btn_restart_audio.clicked.connect(self.restart_audio)
        audio_layout.addWidget(self.btn_restart_audio)
        
        grid.addWidget(audio_box, 0, 0)
        
        # Service toggles
        services_box = QGroupBox("Service Control")
        services_layout = QVBoxLayout(services_box)
        
        self.service_checkboxes = {}
        services = [
            ('audio', 'Audio Engine'),
            ('player', 'Backing Track Player'),
            ('firebase', 'Firebase'),
            ('qr', 'QR Generator'),
            ('ble', 'Bluetooth LE'),
            ('webrtc', 'WebRTC'),
            ('preset_scan', 'Preset Catalog'),
            ('api_server', 'API Server'),
        ]
        
        for name, label in services:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(lambda checked, n=name: self.toggle_service(n, checked))
            services_layout.addWidget(cb)
            self.service_checkboxes[name] = cb
        
        grid.addWidget(services_box, 0, 1)
        
        # QR Code
        qr_box = QGroupBox("QR Code")
        qr_layout = QVBoxLayout(qr_box)
        
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(200, 200)
        self.qr_label.setStyleSheet("background-color: white; border: 1px solid #2D2D2D;")
        qr_layout.addWidget(self.qr_label)
        
        self.btn_refresh_qr = QPushButton("Refresh QR")
        self.btn_refresh_qr.clicked.connect(self.refresh_qr)
        qr_layout.addWidget(self.btn_refresh_qr)
        
        grid.addWidget(qr_box, 1, 0)
        
        # Network info
        net_box = QGroupBox("Network")
        net_layout = QVBoxLayout(net_box)
        
        self.lbl_api = QLabel("API Server: http://localhost:5000")
        self.lbl_api.setStyleSheet("color: #FF9D00; font-weight: bold;")
        net_layout.addWidget(self.lbl_api)
        
        grid.addWidget(net_box, 1, 1)
        
        layout.addLayout(grid)
        layout.addStretch()
    
    def restart_audio(self):
        self.main_window.log("Restarting audio engine...", "info")
        if self.main_window.service_manager:
            asyncio.create_task(self.main_window.service_manager.restart_service('audio'))
    
    def toggle_service(self, name: str, enabled: bool):
        if self.main_window.service_manager:
            if enabled:
                self.main_window.service_manager.enable_service(name)
            else:
                self.main_window.service_manager.disable_service(name)
            self.main_window.log(f"Service {name}: {'enabled' if enabled else 'disabled'}", "info")
    
    def refresh_qr(self):
        self.main_window.log("Refreshing QR...", "info")
        # Would call QR service


class LogsTab(QWidget):
    """System logs with filtering"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()
        self._setup_log_filter()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Toolbar
        toolbar = QHBoxLayout()
        
        self.filters = {}
        categories = ['BOOT', 'AUDIO', 'FIREBASE', 'WEBRTC', 'BLE', 'PLAYER', 'QR', 'PRESET', 'UI', 'SYSTEM']
        
        for cat in categories:
            cb = QCheckBox(cat)
            cb.setChecked(True)
            cb.toggled.connect(self.apply_filter)
            toolbar.addWidget(cb)
            self.filters[cat] = cb
        
        toolbar.addStretch()
        
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear_logs)
        toolbar.addWidget(self.btn_clear)
        
        layout.addLayout(toolbar)
        
        # Log widget
        self.log_widget = QPlainTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0F0F0F;
                border: 1px solid #252525;
                color: #A0A0A0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                line-height: 1.4;
            }
        """)
        layout.addWidget(self.log_widget)
    
    def _setup_log_filter(self):
        pass
    
    def apply_filter(self):
        self.clear_logs()
        # Re-apply filtered messages from history
        # For simplicity, just clear
    
    def clear_logs(self):
        self.log_widget.clear()
    
    def append_message(self, formatted_msg: str):
        # Check filter
        show = True
        for cat, cb in self.filters.items():
            if cb.isChecked() and cat in formatted_msg:
                show = True
                break
            elif not cb.isChecked() and cat in formatted_msg:
                show = False
        
        if show:
            self.log_widget.appendHtml(formatted_msg)
            self.log_widget.verticalScrollBar().setValue(
                self.log_widget.verticalScrollBar().maximum()
            )


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self, logger: Logger):
        super().__init__()
        self.logger = logger
        self.gui_signals = GUISignals()
        self.gui_signals.log_signal.connect(self.log_widget_safe_append)
        self.gui_signals.service_status_signal.connect(self.on_service_status)
        self.gui_signals.bootstrap_phase_signal.connect(self.on_bootstrap_phase)
        self.gui_signals.bootstrap_complete_signal.connect(self.on_bootstrap_complete)
        self.gui_signals.bootstrap_error_signal.connect(self.on_bootstrap_error)
        self.gui_signals.vu_meter_signal.connect(self.on_vu_meter)
        self.gui_signals.waveform_signal.connect(self.on_waveform)
        
        self.service_manager: Optional[ServiceManager] = None
        self.config_loader = None
        
        self.setWindowTitle("GR7 Hub - Guitar Rig 7 Control Center")
        self.setGeometry(100, 100, 1400, 900)
        
        self.init_ui()
        
        # Apply theme
        GR7Style.apply_theme(QApplication.instance())
        self.setStyleSheet(GR7Style.get_stylesheet())
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        header_frame = QFrame()
        header_frame.setFrameShape(QFrame.Shape.StyledPanel)
        header_frame.setStyleSheet(
            "background-color: #222222; border: 1px solid #2D2D2D; min-height: 40px;"
        )
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(15, 0, 15, 0)
        
        title_lbl = QLabel("GUITAR RIG 7 STAGE CONTROL HUB")
        title_lbl.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #E0E0E0; letter-spacing: 1px;"
        )
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        
        self.system_status = QLabel("Initializing...")
        self.system_status.setStyleSheet("color: #888888; font-size: 11px;")
        header_layout.addWidget(self.system_status)
        main_layout.addWidget(header_frame)
        
        # Tabs
        self.tabs = QTabWidget()
        
        self.dashboard_tab = ServiceDashboardTab(self)
        self.audio_monitor_tab = AudioMonitorTab(self)
        self.preset_browser_tab = PresetBrowserTab(self)
        self.player_tab = PlayerTab(self)
        self.settings_tab = SettingsTab(self)
        self.logs_tab = LogsTab(self)
        
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.audio_monitor_tab, "Audio Monitor")
        self.tabs.addTab(self.preset_browser_tab, "Presets")
        self.tabs.addTab(self.player_tab, "Player")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.logs_tab, "Logs")
        
        main_layout.addWidget(self.tabs)
        
        # Status update timer
        self.status_timer = QTimer()
        self.status_timer.setInterval(2000)
        self.status_timer.timeout.connect(self.update_system_status)
        self.status_timer.start()
    
    def set_service_manager(self, service_manager: ServiceManager):
        """Set service manager after bootstrap"""
        self.service_manager = service_manager
        self.logger.log("Service manager connected to UI", "success")
        
        # Register state change callback
        service_manager.register_state_change_callback(self.on_service_state_change)
        
        # Update dashboard
        self.dashboard_tab.update_all_services()
        
        # Update preset browser
        self.preset_browser_tab.update_presets()
        
        # Update player
        self.player_tab.update_player()
    
    def on_service_state_change(self, name: str, old_state: ServiceState, new_state: ServiceState):
        """Handle service state changes"""
        self.logger.log(f"Service {name}: {old_state.value} -> {new_state.value}", "info")
        if self.service_manager:
            status = self.service_manager.get_service_status(name)
            if status:
                self.dashboard_tab.update_service_widget(name, status)
    
    def on_service_status(self, name: str, status: Dict[str, Any]):
        """Handle service status update"""
        self.dashboard_tab.update_service_widget(name, status)
    
    def on_bootstrap_phase(self, phase: str):
        """Handle bootstrap phase change"""
        self.system_status.setText(f"Bootstrap: {phase}")
        self.logger.log(f"Bootstrap phase: {phase}", "info")
    
    def on_bootstrap_complete(self, result: Dict[str, Any]):
        """Handle bootstrap completion"""
        success = result.get('success', False)
        if success:
            self.system_status.setText("All services started successfully")
            self.logger.log("Bootstrap completed successfully", "success")
        else:
            self.system_status.setText("Bootstrap completed with errors")
            self.logger.log("Bootstrap completed with errors", "error")
        
        # Update service checkboxes
        if self.service_manager:
            statuses = self.service_manager.get_all_status()
            for name, status in statuses.items():
                cb = self.settings_tab.service_checkboxes.get(name)
                if cb:
                    cb.setChecked(status.get('state') != 'disabled')
    
    def on_bootstrap_error(self, error: str):
        """Handle bootstrap error"""
        self.system_status.setText(f"Bootstrap error: {error}")
        self.logger.log(f"Bootstrap error: {error}", "error")
    
    def on_vu_meter(self, vu_data: Dict[str, float]):
        """Handle VU meter update"""
        # Audio monitor tab handles this via timer
        pass
    
    def on_waveform(self, waveform_data: Dict[str, list]):
        """Handle waveform update"""
        pass
    
    def update_system_status(self):
        """Update system status in header"""
        if not self.service_manager:
            return
        
        try:
            statuses = self.service_manager.get_all_status()
            running = sum(1 for s in statuses.values() if s.get('state') == 'running')
            degraded = sum(1 for s in statuses.values() if s.get('state') == 'degraded')
            failed = sum(1 for s in statuses.values() if s.get('state') == 'failed')
            total = len(statuses)
            
            self.system_status.setText(
                f"Services: {running}/{total} running | "
                f"{degraded} degraded | {failed} failed"
            )
        except Exception as e:
            self.logger.log(f"Status update error: {e}", "error")
    
    def log(self, message: str, level: str = "info"):
        """Log message"""
        self.logger.log(message, level)
        self.gui_signals.log_signal.emit(message, level)
    
    def log_widget_safe_append(self, message: str, level: str):
        """Append to log widget (thread-safe)"""
        color = "#A0A0A0"
        if level == "error":
            color = "#FF3333"
        elif level == "success":
            color = "#33FF33"
        elif level == "warning":
            color = "#FF9D00"
        
        formatted_msg = f"<span style='color:{color};'>[{level.upper()}] {message}</span>"
        self.logs_tab.append_message(formatted_msg)
    
    def closeEvent(self, event):
        """Handle close event"""
        self.logger.log("Shutting down...", "info")
        
        if self.service_manager:
            # Stop all services
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.service_manager.stop_all())
            loop.close()
        
        event.accept()


# For backward compatibility
def create_main_window(logger: Logger) -> MainWindow:
    """Factory function to create main window"""
    return MainWindow(logger)