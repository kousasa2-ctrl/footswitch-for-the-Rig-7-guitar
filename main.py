#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GR7 Hub - Main Application
===========================
Guitar Rig 7 Hub с VST3 хостингом, каталогом пресетов и мобильным управлением.
"""

import sys
import threading
from pathlib import Path

# PyQt6
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QFrame, QProgressBar, QTextEdit,
    QGroupBox, QGridLayout, QComboBox, QSpinBox, QCheckBox, QSplitter,
    QListWidget, QListWidgetItem, QSlider, QScrollArea, QFrame as QFrame2
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt6.QtGui import (
    QColor, QPalette, QFont, QBrush, QLinearGradient, QPainter,
    QPen, QCursor, QIcon, QPixmap
)

# Модули приложения
from core import StateManager, ConfigLoader, Logger
from services import PluginService, AudioService, MIDIService, WebRTCService, PlayerService, PresetCatalog
from api.server import APIServer
from utils import QRGenerator


# =============================================================================
# СТИЛИ И КОНСТАНТЫ
# =============================================================================

class GR7Style:
    """Стили в стиле Guitar Rig 7"""

    @staticmethod
    def apply_stylesheet(app):
        """Применение стиля Guitar Rig 7"""
        app.setStyle("Fusion")

        # Цветовая палитра Guitar Rig 7
        palette = QPalette()

        # Основные цвета
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 35))
        palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 30))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 40))
        palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Button, QColor(40, 40, 45))
        palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        palette.setColor(QPalette.ColorRole.Link, QColor(0, 200, 200))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 180, 180))
        palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)

        app.setPalette(palette)

    @staticmethod
    def create_gradient_background(widget):
        """Создание градиентного фона"""
        widget.setAutoFillBackground(True)
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 35))
        widget.setPalette(palette)


# =============================================================================
# ВИЗУАЛЬНЫЕ КОМПОНЕНТЫ
# =============================================================================

class LogWidget(QTextEdit):
    """Виджет логов"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a20;
                color: #00ff00;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #00ccaa;
                border-radius: 4px;
                padding: 8px;
            }
        """)

    def log(self, message: str, level: str = "info"):
        """Добавление сообщения в лог"""
        colors = {
            "info": "#00ff00",
            "success": "#00ccaa",
            "error": "#ff4444",
            "warning": "#ffaa00",
            "debug": "#0088ff"
        }

        color = colors.get(level, "#00ff00")
        self.append(f'<span style="color: {color}">[{level.upper()}] {message}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class PresetListWidget(QListWidget):
    """Список пресетов в стиле Guitar Rig"""

    preset_selected = pyqtSignal(str)
    preset_double_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setStyleSheet("""
            QListWidget {
                background-color: #1a1a20;
                border: 1px solid #00ccaa;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #2a2a30;
                color: #cccccc;
            }
            QListWidget::item:selected {
                background-color: #00ccaa;
                color: #000000;
                font-weight: bold;
            }
            QListWidget::item:hover {
                background-color: #2a2a35;
            }
        """)

    def add_preset(self, preset_id: str, name: str, category: str = ""):
        """Добавление пресета"""
        item = QListWidgetItem(f"{name} {f'[{category}]' if category else ''}")
        item.setData(Qt.ItemDataRole.UserRole, preset_id)
        self.addItem(item)

    def mouseDoubleClickEvent(self, event):
        """Двойной клик"""
        item = self.itemAt(event.pos())
        if item:
            self.preset_double_clicked.emit(item.data(Qt.ItemDataRole.UserRole))
        super().mouseDoubleClickEvent(event)


class RackChainWidget(QFrame):
    """Виджет rack chain"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #1a1a20;
                border: 1px solid #00ccaa;
                border-radius: 4px;
                padding: 10px;
            }
        """)

    def set_rack_chain(self, rack_chain: list):
        """Установка rack chain"""
        layout = QVBoxLayout()
        layout.setSpacing(5)

        if not rack_chain:
            label = QLabel("Нет rack chain")
            label.setStyleSheet("color: #666666; font-style: italic;")
            layout.addWidget(label)
        else:
            for module in rack_chain:
                module_frame = QFrame()
                module_frame.setFrameShape(QFrame.Shape.StyledPanel)
                module_frame.setStyleSheet("""
                    QFrame {
                        background-color: #252530;
                        border: 1px solid #008877;
                        border-radius: 3px;
                        padding: 5px;
                    }
                """)

                module_layout = QHBoxLayout()
                module_layout.setSpacing(5)

                name_label = QLabel(module.get('name', 'Unknown'))
                name_label.setStyleSheet("color: #00ccaa; font-weight: bold;")
                module_layout.addWidget(name_label)

                if 'parameters' in module:
                    for param_name, param_value in module['parameters'].items():
                        param_label = QLabel(f"{param_name}: {param_value:.2f}")
                        param_label.setStyleSheet("color: #888888; font-size: 10px;")
                        module_layout.addWidget(param_label)

                module_frame.setLayout(module_layout)
                layout.addWidget(module_frame)

        layout.addStretch()
        self.setLayout(layout)


class TransportWidget(QFrame):
    """Виджет управления транспортом"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #1a1a20;
                border: 1px solid #00ccaa;
                border-radius: 4px;
                padding: 10px;
            }
        """)

    def set_transport_state(self, current_preset: dict, current_track: dict, player_state: dict):
        """Установка состояния транспорта"""
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # Пресет
        preset_group = QGroupBox("Текущий пресет")
        preset_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        preset_layout = QVBoxLayout()

        if current_preset:
            name_label = QLabel(current_preset.get('name', 'Не выбран'))
            name_label.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
            preset_layout.addWidget(name_label)

            category_label = QLabel(f"Категория: {current_preset.get('category', 'N/A')}")
            category_label.setStyleSheet("color: #888888; font-size: 11px;")
            preset_layout.addWidget(category_label)
        else:
            label = QLabel("Пресет не выбран")
            label.setStyleSheet("color: #666666; font-style: italic;")
            preset_layout.addWidget(label)

        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

        # Трек
        track_group = QGroupBox("Backing Track")
        track_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        track_layout = QVBoxLayout()

        if current_track:
            name_label = QLabel(current_track.get('name', 'Не выбран'))
            name_label.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
            track_layout.addWidget(name_label)

            if 'position' in current_track and 'duration' in current_track:
                pos_label = QLabel(f"Позиция: {current_track['position']:.1f}s / {current_track['duration']:.1f}s")
                pos_label.setStyleSheet("color: #888888; font-size: 11px;")
                track_layout.addWidget(pos_label)
        else:
            label = QLabel("Трек не выбран")
            label.setStyleSheet("color: #666666; font-style: italic;")
            track_layout.addWidget(label)

        track_group.setLayout(track_layout)
        layout.addWidget(track_group)

        # Статус плеера
        state_label = QLabel(f"Состояние: {player_state.get('state', 'stopped')}")
        state_label.setStyleSheet("color: #ffaa00; font-size: 11px;")
        layout.addWidget(state_label)

        layout.addStretch()
        self.setLayout(layout)


# =============================================================================
# ВКЛАДКИ GUI
# =============================================================================

class PresetBrowserTab(QWidget):
    """Вкладка браузера пресетов"""

    def __init__(self, preset_catalog, plugin_service, logger, parent=None):
        super().__init__(parent)
        self.preset_catalog = preset_catalog
        self.plugin_service = plugin_service
        self.logger = logger
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)

        # Левая панель - фильтры и поиск
        left_panel = QFrame()
        left_panel.setFrameShape(QFrame.Shape.StyledPanel)
        left_panel.setStyleSheet("""
            QFrame {
                background-color: #1a1a20;
                border: 1px solid #00ccaa;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)

        # Заголовок
        title = QLabel("БРАУЗЕР ПРЕСЕТОВ")
        title.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #00ccaa;
                text-align: center;
                padding: 5px;
                border-bottom: 1px solid #008877;
            }
        """)
        left_layout.addWidget(title)

        # Категории
        cat_group = QGroupBox("Категории")
        cat_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        cat_layout = QVBoxLayout()

        self.cat_factory = QCheckBox("Заводские")
        self.cat_factory.setChecked(True)
        self.cat_factory.setStyleSheet("color: #cccccc;")
        cat_layout.addWidget(self.cat_factory)

        self.cat_user = QCheckBox("Пользовательские")
        self.cat_user.setChecked(True)
        self.cat_user.setStyleSheet("color: #cccccc;")
        cat_layout.addWidget(self.cat_user)

        self.cat_favorites = QCheckBox("Избранное")
        self.cat_favorites.setChecked(True)
        self.cat_favorites.setStyleSheet("color: #cccccc;")
        cat_layout.addWidget(self.cat_favorites)

        self.cat_recent = QCheckBox("Недавние")
        self.cat_recent.setChecked(True)
        self.cat_recent.setStyleSheet("color: #cccccc;")
        cat_layout.addWidget(self.cat_recent)

        cat_group.setLayout(cat_layout)
        left_layout.addWidget(cat_group)

        # Поиск
        search_group = QGroupBox("Поиск")
        search_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        search_layout = QVBoxLayout()

        self.search_input = QComboBox()
        self.search_input.setEditable(True)
        self.search_input.addItems(["", "Clean", "Distortion", "Reverb", "Delay", "Compressor"])
        self.search_input.setStyleSheet("""
            QComboBox {
                background-color: #252530;
                color: #ffffff;
                border: 1px solid #008877;
                border-radius: 3px;
                padding: 5px;
            }
            QComboBox::drop-down {
                border: none;
            }
        """)
        search_layout.addWidget(self.search_input)

        search_group.setLayout(search_layout)
        left_layout.addWidget(search_group)

        # Кнопки управления
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(5)

        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #008877;
                color: #ffffff;
                font-weight: bold;
                padding: 8px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #00aa99;
            }
        """)
        self.btn_refresh.clicked.connect(self._refresh_presets)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_next = QPushButton("Следующий")
        self.btn_next.setStyleSheet("""
            QPushButton {
                background-color: #008877;
                color: #ffffff;
                font-weight: bold;
                padding: 8px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #00aa99;
            }
        """)
        self.btn_next.clicked.connect(self._next_preset)
        btn_layout.addWidget(self.btn_next)

        self.btn_prev = QPushButton("Предыдущий")
        self.btn_prev.setStyleSheet("""
            QPushButton {
                background-color: #008877;
                color: #ffffff;
                font-weight: bold;
                padding: 8px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #00aa99;
            }
        """)
        self.btn_prev.clicked.connect(self._prev_preset)
        btn_layout.addWidget(self.btn_prev)

        left_layout.addLayout(btn_layout)
        left_layout.addStretch()

        left_panel.setLayout(left_layout)
        layout.addWidget(left_panel, 1)

        # Центральная панель - список пресетов
        center_panel = QFrame()
        center_panel.setFrameShape(QFrame.Shape.StyledPanel)
        center_panel.setStyleSheet("""
            QFrame {
                background-color: #1a1a20;
                border: 1px solid #00ccaa;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        center_layout = QVBoxLayout()
        center_layout.setSpacing(5)

        self.preset_list = PresetListWidget()
        self.preset_list.preset_double_clicked.connect(self._on_preset_double_clicked)
        center_layout.addWidget(self.preset_list)

        center_panel.setLayout(center_layout)
        layout.addWidget(center_panel, 2)

        # Правая панель - rack chain
        right_panel = QFrame()
        right_panel.setFrameShape(QFrame.Shape.StyledPanel)
        right_panel.setStyleSheet("""
            QFrame {
                background-color: #1a1a20;
                border: 1px solid #00ccaa;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(5)

        title2 = QLabel("RACK CHAIN")
        title2.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #00ccaa;
                text-align: center;
                padding: 5px;
                border-bottom: 1px solid #008877;
            }
        """)
        right_layout.addWidget(title2)

        self.rack_chain = RackChainWidget()
        right_layout.addWidget(self.rack_chain)

        right_panel.setLayout(right_layout)
        layout.addWidget(right_panel, 1)

        self.setLayout(layout)

    def _refresh_presets(self):
        """Обновление списка пресетов"""
        self.preset_list.clear()

        # Собираем пресеты из выбранных категорий
        categories = []
        if self.cat_factory.isChecked():
            categories.append("factory")
        if self.cat_user.isChecked():
            categories.append("user")
        if self.cat_favorites.isChecked():
            categories.append("favorites")
        if self.cat_recent.isChecked():
            categories.append("recent")

        search_query = self.search_input.currentText()

        for cat in categories:
            presets = self.preset_catalog.get_all_presets()
            for preset in presets:
                if preset.category.value == cat:
                    if search_query and search_query.lower() not in preset.name.lower():
                        continue
                    self.preset_list.add_preset(preset.id, preset.name, preset.category.value)

        self.logger.log(f"Обновлен список пресетов: {self.preset_list.count()}", "info")

    def _on_preset_double_clicked(self, preset_id: str):
        """Двойной клик по пресету"""
        if self.preset_catalog.select_preset(preset_id):
            self.logger.log(f"Выбран пресет: {preset_id}", "success")
            self._update_rack_chain()

    def _next_preset(self):
        """Следующий пресет"""
        preset_id = self.preset_catalog.next_preset()
        if preset_id:
            self.logger.log(f"Следующий пресет: {preset_id}", "info")
            self._update_rack_chain()

    def _prev_preset(self):
        """Предыдущий пресет"""
        preset_id = self.preset_catalog.prev_preset()
        if preset_id:
            self.logger.log(f"Предыдущий пресет: {preset_id}", "info")
            self._update_rack_chain()

    def _update_rack_chain(self):
        """Обновление rack chain"""
        current_preset = self.preset_catalog.get_current_preset()
        if current_preset:
            rack_chain = self.preset_catalog.get_rack_chain(current_preset.id)
            self.rack_chain.set_rack_chain(rack_chain or [])


class PlayerTab(QWidget):
    """Вкладка плеера"""

    def __init__(self, player_service, logger, parent=None):
        super().__init__(parent)
        self.player_service = player_service
        self.logger = logger
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Заголовок
        title = QLabel("BACKING TRACK PLAYER")
        title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #00ccaa;
                text-align: center;
                padding: 10px;
                border-bottom: 2px solid #008877;
            }
        """)
        layout.addWidget(title)

        # Список треков
        track_group = QGroupBox("Список треков")
        track_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        track_layout = QVBoxLayout()

        self.track_list = QListWidget()
        self.track_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a20;
                border: 1px solid #008877;
                border-radius: 3px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #2a2a30;
                color: #cccccc;
            }
            QListWidget::item:selected {
                background-color: #00ccaa;
                color: #000000;
                font-weight: bold;
            }
        """)
        self.track_list.itemDoubleClicked.connect(self._on_track_double_clicked)
        track_layout.addWidget(self.track_list)

        track_group.setLayout(track_layout)
        layout.addWidget(track_group)

        # Кнопки управления
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(5)

        self.btn_play = QPushButton("▶ Воспроизвести")
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #00cc00;
                color: #000000;
                font-weight: bold;
                padding: 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #00ee00;
            }
        """)
        self.btn_play.clicked.connect(self._play_track)
        btn_layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⬛ Стоп")
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #cc0000;
                color: #ffffff;
                font-weight: bold;
                padding: 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #ee0000;
            }
        """)
        self.btn_stop.clicked.connect(self._stop_track)
        btn_layout.addWidget(self.btn_stop)

        self.btn_next = QPushButton("Следующий")
        self.btn_next.setStyleSheet("""
            QPushButton {
                background-color: #008877;
                color: #ffffff;
                font-weight: bold;
                padding: 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #00aa99;
            }
        """)
        self.btn_next.clicked.connect(self._next_track)
        btn_layout.addWidget(self.btn_next)

        self.btn_prev = QPushButton("Предыдущий")
        self.btn_prev.setStyleSheet("""
            QPushButton {
                background-color: #008877;
                color: #ffffff;
                font-weight: bold;
                padding: 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #00aa99;
            }
        """)
        self.btn_prev.clicked.connect(self._prev_track)
        btn_layout.addWidget(self.btn_prev)

        layout.addLayout(btn_layout)

        # Громкость
        vol_group = QGroupBox("Громкость")
        vol_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        vol_layout = QHBoxLayout()

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: #2a2a30;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00ccaa;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
        """)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        vol_layout.addWidget(self.vol_slider)

        vol_group.setLayout(vol_layout)
        layout.addWidget(vol_group)

        # Статус
        self.status_label = QLabel("Готов к работе")
        self.status_label.setStyleSheet("color: #00ccaa; font-size: 12px;")
        layout.addWidget(self.status_label)

        layout.addStretch()
        self.setLayout(layout)

    def _load_tracks(self):
        """Загрузка треков"""
        self.track_list.clear()
        tracks = self.player_service.get_all_tracks()
        for track in tracks:
            self.track_list.addItem(f"{track.name} ({track.format.upper()})")

    def _on_track_double_clicked(self, item):
        """Двойной клик по треку"""
        row = self.track_list.row(item)
        tracks = self.player_service.get_all_tracks()
        if row < len(tracks):
            track_id = tracks[row].id
            if self.player_service.play_track(track_id):
                self.logger.log(f"Воспроизведение: {track_id}", "success")
                self.status_label.setText(f"Воспроизведение: {tracks[row].name}")

    def _play_track(self):
        """Воспроизведение текущего трека"""
        current_track = self.player_service.get_current_track()
        if current_track:
            if self.player_service.play_track(current_track.id):
                self.logger.log(f"Воспроизведение: {current_track.id}", "success")
                self.status_label.setText(f"Воспроизведение: {current_track.name}")
        else:
            self.logger.log("Нет выбранного трека", "warning")

    def _stop_track(self):
        """Остановка"""
        self.player_service.stop()
        self.status_label.setText("Остановлено")
        self.logger.log("Воспроизведение остановлено", "info")

    def _next_track(self):
        """Следующий трек"""
        track_id = self.player_service.next_track()
        if track_id:
            self.logger.log(f"Следующий трек: {track_id}", "info")
            self._load_tracks()
            self.status_label.setText(f"Следующий: {track_id}")

    def _prev_track(self):
        """Предыдущий трек"""
        track_id = self.player_service.prev_track()
        if track_id:
            self.logger.log(f"Предыдущий трек: {track_id}", "info")
            self._load_tracks()
            self.status_label.setText(f"Предыдущий: {track_id}")

    def _on_volume_changed(self, value):
        """Изменение громкости"""
        self.player_service.set_volume(value / 100.0)


class NetworkTab(QWidget):
    """Вкладка сети"""

    def __init__(self, webrtc_service, logger, parent=None):
        super().__init__(parent)
        self.webrtc_service = webrtc_service
        self.logger = logger
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Заголовок
        title = QLabel("СЕТЬ И МОБИЛЬНОЕ УПРАВЛЕНИЕ")
        title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #00ccaa;
                text-align: center;
                padding: 10px;
                border-bottom: 2px solid #008877;
            }
        """)
        layout.addWidget(title)

        # Статус
        status_group = QGroupBox("Статус соединения")
        status_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        status_layout = QVBoxLayout()

        self.connection_status = QLabel("Не подключен")
        self.connection_status.setStyleSheet("color: #ff4444; font-size: 14px; font-weight: bold;")
        status_layout.addWidget(self.connection_status)

        self.room_id_label = QLabel("Room ID: -")
        self.room_id_label.setStyleSheet("color: #888888; font-size: 12px;")
        status_layout.addWidget(self.room_id_label)

        self.api_url_label = QLabel("API URL: http://localhost:5000")
        self.api_url_label.setStyleSheet("color: #888888; font-size: 12px;")
        status_layout.addWidget(self.api_url_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Создание комнаты
        create_group = QGroupBox("Создать комнату")
        create_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        create_layout = QVBoxLayout()

        self.create_room_btn = QPushButton("Создать WebRTC комнату")
        self.create_room_btn.setStyleSheet("""
            QPushButton {
                background-color: #008877;
                color: #ffffff;
                font-weight: bold;
                padding: 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #00aa99;
            }
        """)
        self.create_room_btn.clicked.connect(self._create_room)
        create_layout.addWidget(self.create_room_btn)

        create_group.setLayout(create_layout)
        layout.addWidget(create_group)

        # QR Code
        qr_group = QGroupBox("QR Code")
        qr_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        qr_layout = QVBoxLayout()

        self.qr_label = QLabel("QR Code появится здесь")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a20;
                color: #888888;
                font-size: 12px;
                padding: 20px;
                border: 1px dashed #008877;
                border-radius: 4px;
            }
        """)
        qr_layout.addWidget(self.qr_label)

        qr_group.setLayout(qr_layout)
        layout.addWidget(qr_group)

        layout.addStretch()
        self.setLayout(layout)

    def _create_room(self):
        """Создание комнаты"""
        room_id = self.webrtc_service.create_room()
        if room_id:
            self.room_id_label.setText(f"Room ID: {room_id}")
            self.logger.log(f"Комната создана: {room_id}", "success")

            # Генерация QR Code
            from utils.qr_generator import QRGenerator
            qr_gen = QRGenerator()
            qr_gen.generate_qr_code(f"http://localhost:5000?room={room_id}")
            self.qr_label.setText(f"Room ID: {room_id}\n\nОтсканируйте для подключения")
            self.qr_label.setStyleSheet("""
                QLabel {
                    background-color: #1a1a20;
                    color: #00ccaa;
                    font-size: 12px;
                    padding: 20px;
                    border: 1px solid #00ccaa;
                    border-radius: 4px;
                }
            """)

    def update_status(self, status: dict):
        """Обновление статуса"""
        if status.get('ice_connected'):
            self.connection_status.setText("Подключено")
            self.connection_status.setStyleSheet("color: #00cc00; font-size: 14px; font-weight: bold;")
        else:
            self.connection_status.setText("Не подключен")
            self.connection_status.setStyleSheet("color: #ff4444; font-size: 14px; font-weight: bold;")


class SettingsTab(QWidget):
    """Вкладка настроек"""

    def __init__(self, config, logger, parent=None):
        super().__init__(parent)
        self.config = config
        self.logger = logger
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Заголовок
        title = QLabel("НАСТРОЙКИ")
        title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #00ccaa;
                text-align: center;
                padding: 10px;
                border-bottom: 2px solid #008877;
            }
        """)
        layout.addWidget(title)

        # VST3 Path
        vst3_group = QGroupBox("Путь к VST3 плагину")
        vst3_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        vst3_layout = QVBoxLayout()

        vst3_path = self.config.get('vst3', 'path', '')
        self.vst3_entry = QLabel(vst3_path if vst3_path else "Не указан")
        self.vst3_entry.setStyleSheet("color: #888888; font-size: 11px; padding: 5px;")
        vst3_layout.addWidget(self.vst3_entry)

        vst3_group.setLayout(vst3_layout)
        layout.addWidget(vst3_group)

        # Папка пресетов
        preset_group = QGroupBox("Папка с пресетами")
        preset_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        preset_layout = QVBoxLayout()

        preset_folder = self.config.get('gr7', 'preset_folder', '')
        self.preset_entry = QLabel(preset_folder if preset_folder else "Не указан")
        self.preset_entry.setStyleSheet("color: #888888; font-size: 11px; padding: 5px;")
        preset_layout.addWidget(self.preset_entry)

        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

        # Папка с треками
        track_group = QGroupBox("Папка с backing tracks")
        track_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        track_layout = QVBoxLayout()

        songs_folder = self.config.get('gr7', 'songs', '')
        self.songs_entry = QLabel(songs_folder if songs_folder else "Не указан")
        self.songs_entry.setStyleSheet("color: #888888; font-size: 11px; padding: 5px;")
        track_layout.addWidget(self.songs_entry)

        track_group.setLayout(track_layout)
        layout.addWidget(track_group)

        # API Port
        api_group = QGroupBox("API порт")
        api_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        api_layout = QVBoxLayout()

        api_port = self.config.get('wifi', 'port', '5000')
        self.api_entry = QLabel(f"Порт: {api_port}")
        self.api_entry.setStyleSheet("color: #888888; font-size: 11px; padding: 5px;")
        api_layout.addWidget(self.api_entry)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # Debug
        debug_group = QGroupBox("Отладка")
        debug_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #00ccaa;
                border: 1px solid #008877;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        debug_layout = QVBoxLayout()

        self.debug_info = QLabel("GR7 Hub v3.0 - Server Architecture")
        self.debug_info.setStyleSheet("color: #008877; font-size: 11px;")
        debug_layout.addWidget(self.debug_info)

        debug_group.setLayout(debug_layout)
        layout.addWidget(debug_group)

        layout.addStretch()
        self.setLayout(layout)


class TransportTab(QWidget):
    """Вкладка транспорта"""

    def __init__(self, preset_catalog, player_service, logger, parent=None):
        super().__init__(parent)
        self.preset_catalog = preset_catalog
        self.player_service = player_service
        self.logger = logger
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Заголовок
        title = QLabel("ТРАНСПОРТ")
        title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #00ccaa;
                text-align: center;
                padding: 10px;
                border-bottom: 2px solid #008877;
            }
        """)
        layout.addWidget(title)

        # Виджет транспорта
        self.transport_widget = TransportWidget()
        layout.addWidget(self.transport_widget)

        layout.addStretch()
        self.setLayout(layout)

    def update_transport(self):
        """Обновление транспорта"""
        current_preset = self.preset_catalog.get_current_preset()
        current_track = self.player_service.get_current_track()
        player_state = self.player_service.get_state()
        self.transport_widget.set_transport_state(
            current_preset.to_dict() if current_preset else None,
            current_track.to_dict() if current_track else None,
            player_state
        )


# =============================================================================
# ГЛАВНОЕ ОКНО
# =============================================================================

class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GR7 Hub - Guitar Rig 7 Control Hub")
        self.setGeometry(100, 100, 1200, 800)

        # Инициализация компонентов
        self.config = ConfigLoader()
        self.logger = Logger("GR7Hub")
        self.state_manager = StateManager()

        # Сервисы
        self.preset_catalog = PresetCatalog(self.config, self.logger)
        self.player_service = PlayerService(self.config, self.logger)
        self.plugin_service = PluginService(self.config, self.state_manager, self.logger, self.preset_catalog)
        self.audio_service = AudioService(self.config, self.state_manager, self.logger)
        self.midi_service = MIDIService(self.config, self.state_manager, self.logger)
        self.webrtc_service = WebRTCService(self.config, self.state_manager, self.logger)
        self.api_server = APIServer(self.config, self.logger, self.preset_catalog, self.player_service, self.plugin_service)

        # QR Generator
        self.qr_generator = QRGenerator()

        # Инициализация UI
        self._init_ui()

        # Запуск фоновых сервисов
        self._start_background_services()

    def _init_ui(self):
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Главный layout
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)

        # Верхняя панель
        top_bar = QFrame()
        top_bar.setStyleSheet("""
            QFrame {
                background-color: #1a1a20;
                border-bottom: 2px solid #00ccaa;
                padding: 10px;
            }
        """)
        top_layout = QHBoxLayout()

        title = QLabel("GR7 HUB")
        title.setStyleSheet("""
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #00ccaa;
            }
        """)
        top_layout.addWidget(title)

        top_layout.addStretch()

        # Статус системы
        self.system_status = QLabel("Инициализация...")
        self.system_status.setStyleSheet("""
            QLabel {
                color: #008877;
                font-size: 12px;
            }
        """)
        top_layout.addWidget(self.system_status)

        top_bar.setLayout(top_layout)
        main_layout.addWidget(top_bar)

        # Tab Widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #00ccaa;
                border-radius: 4px;
                background-color: #1a1a20;
            }
            QTabBar::tab {
                background-color: #2a2a30;
                color: #00ccaa;
                padding: 10px 20px;
                margin-right: 2px;
                border-radius: 4px 4px 0 0;
            }
            QTabBar::tab:selected {
                background-color: #1a1a20;
                border-bottom: 2px solid #00ccaa;
            }
            QTabBar::tab:hover {
                background-color: #3a3a40;
            }
        """)

        # Вкладки
        self.preset_browser_tab = PresetBrowserTab(self.preset_catalog, self.plugin_service, self.logger)
        self.player_tab = PlayerTab(self.player_service, self.logger)
        self.network_tab = NetworkTab(self.webrtc_service, self.logger)
        self.settings_tab = SettingsTab(self.config, self.logger)
        self.transport_tab = TransportTab(self.preset_catalog, self.player_service, self.logger)

        self.tab_widget.addTab(self.preset_browser_tab, "Пресеты")
        self.tab_widget.addTab(self.player_tab, "Плеер")
        self.tab_widget.addTab(self.transport_tab, "Транспорт")
        self.tab_widget.addTab(self.network_tab, "Сеть")
        self.tab_widget.addTab(self.settings_tab, "Настройки")

        main_layout.addWidget(self.tab_widget)

        # Лог
        log_label = QLabel("ЖУРНАЛ СОБЫТИЙ:")
        log_label.setStyleSheet("""
            QLabel {
                color: #00ccaa;
                font-size: 12px;
                font-weight: bold;
            }
        """)
        main_layout.addWidget(log_label)

        self.log_widget = LogWidget()
        main_layout.addWidget(self.log_widget)

        central_widget.setLayout(main_layout)

        # Таймер обновления статуса
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)

    def _start_background_services(self):
        """Запуск всех сервисов в фоновом потоке"""
        self.logger.log("[BOOT] GUI создан", "info")
        self.logger.log("[BOOT] Запуск фоновых сервисов", "info")

        threading.Thread(
            target=self._init_services,
            daemon=True,
            name="BackgroundServices"
        ).start()

    def _init_services(self):
        """Инициализация всех сервисов в фоновом потоке"""
        try:
            # Preset Catalog
            self.logger.log("[BOOT] PresetCatalog init start", "info")
            if self.preset_catalog.initialize():
                self.logger.log("[BOOT] PresetCatalog init complete", "info")
            else:
                self.logger.log("[BOOT] PresetCatalog init failed", "error")

            # Player Service
            self.logger.log("[BOOT] PlayerService init start", "info")
            if self.player_service.initialize():
                self.logger.log("[BOOT] PlayerService init complete", "info")
            else:
                self.logger.log("[BOOT] PlayerService init failed", "error")

            # VST3
            self.logger.log("[BOOT] VST3 init start", "info")
            if self.plugin_service.initialize():
                self.logger.log("[BOOT] VST3 init complete", "info")
            else:
                self.logger.log("[BOOT] VST3 init failed", "error")

            # Audio
            self.logger.log("[BOOT] Audio init start", "info")
            if self.audio_service.initialize():
                self.logger.log("[BOOT] Audio init complete", "info")
            else:
                self.logger.log("[BOOT] Audio init failed", "error")

            # MIDI
            self.logger.log("[BOOT] MIDI init start", "info")
            if self.midi_service.initialize():
                self.logger.log("[BOOT] MIDI init complete", "info")
            else:
                self.logger.log("[BOOT] MIDI init failed", "error")

            # WebRTC
            self.logger.log("[BOOT] WebRTC init start", "info")
            if self.webrtc_service.initialize():
                self.logger.log("[BOOT] WebRTC init complete", "info")
            else:
                self.logger.log("[BOOT] WebRTC init failed", "error")

            # API Server
            self.logger.log("[BOOT] API Server init start", "info")
            if self.api_server.initialize():
                self.api_server.start()
                self.logger.log("[BOOT] API Server started", "info")
            else:
                self.logger.log("[BOOT] API Server init failed", "error")

            self.logger.log("[BOOT] Все сервисы инициализированы", "info")

        except Exception as e:
            self.logger.log(f"[BOOT] Service initialization error: {e}", "error")
            import traceback
            self.logger.log(traceback.format_exc(), "error")

    def _update_status(self):
        """Обновление статуса"""
        # Обновление вкладок
        self.preset_browser_tab._update_rack_chain()
        self.transport_tab.update_transport()

        # Обновление статуса системы
        state = self.state_manager.state.get_state_dict()

        status_text = f"VST3: {'OK' if state.get('plugin_loaded') else 'NO'} | "
        status_text += f"Audio: {'OK' if state.get('audio_engine_active') else 'NO'} | "
        status_text += f"MIDI: {'OK' if state.get('midi_active') else 'NO'} | "
        status_text += f"WebRTC: {'OK' if state.get('webrtc_active') else 'NO'} | "
        status_text += f"API: {'OK' if self.api_server.is_running() else 'NO'}"
        self.system_status.setText(status_text)

    def log(self, message: str, level: str = "info"):
        """Логирование"""
        self.log_widget.log(message, level)

    def closeEvent(self, event):
        """Закрытие приложения"""
        self.api_server.stop()
        self.logger.log("Приложение закрыто", "info")
        event.accept()


def main():
    """Точка входа"""
    app = QApplication(sys.argv)

    # Применение стиля Guitar Rig 7
    GR7Style.apply_stylesheet(app)

    # Создание и запуск окна
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()