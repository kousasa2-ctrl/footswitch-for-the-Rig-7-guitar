import threading
import sys

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QFrame, QProgressBar, QTextEdit,
    QGroupBox, QGridLayout, QComboBox, QSlider, QListWidget, QListWidgetItem,
    QSplitter
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QPalette, QTextCursor

from core import StateManager, ConfigLoader, Logger
from services import (
    PluginService, AudioService, MIDIService,
    WebRTCService, PlayerService, PresetCatalog
)
from api.server import APIServer
from utils.qr_generator import QRGenerator


class GUISignals(QObject):
    log_signal = pyqtSignal(str, str)


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

            QTextEdit {
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
        """


class PresetBrowserTab(QWidget):
    """Вкладка браузера пресетов"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        search_box = QGroupBox("Поиск пресетов")
        search_layout = QVBoxLayout(search_box)
        self.search_input = QTextEdit()
        self.search_input.setMaximumHeight(30)
        self.search_input.setPlaceholderText("Введите имя пресета...")
        search_layout.addWidget(self.search_input)
        left_layout.addWidget(search_box)

        presets_box = QGroupBox("Доступные пресеты")
        presets_layout = QVBoxLayout(presets_box)
        self.preset_list = QListWidget()
        self.preset_list.itemSelectionChanged.connect(self._on_preset_selected)
        presets_layout.addWidget(self.preset_list)
        left_layout.addWidget(presets_box)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        info_box = QGroupBox("Информация о пресете")
        info_layout = QGridLayout(info_box)
        info_layout.addWidget(QLabel("Название:"), 0, 0)
        self.lbl_name = QLabel("-")
        self.lbl_name.setStyleSheet("color: #FF9D00; font-weight: bold;")
        info_layout.addWidget(self.lbl_name, 0, 1)

        info_layout.addWidget(QLabel("Категория:"), 1, 0)
        self.lbl_category = QLabel("-")
        info_layout.addWidget(self.lbl_category, 1, 1)

        info_layout.addWidget(QLabel("Компоненты:"), 2, 0)
        self.lbl_components = QLabel("-")
        info_layout.addWidget(self.lbl_components, 2, 1)
        right_layout.addWidget(info_box)

        rack_box = QGroupBox("Текущая стойка эффектов (Rack Chain)")
        rack_layout = QVBoxLayout(rack_box)
        self.rack_list = QListWidget()
        rack_layout.addWidget(self.rack_list)

        btn_layout = QHBoxLayout()
        self.btn_load = QPushButton("Загрузить в Guitar Rig")
        self.btn_load.setObjectName("accent-btn")
        self.btn_load.clicked.connect(self._on_load_clicked)
        btn_layout.addWidget(self.btn_load)
        rack_layout.addLayout(btn_layout)

        right_layout.addWidget(rack_box)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([450, 750])

        layout.addWidget(splitter)

    def update_presets(self):
        self.preset_list.clear()
        presets = self.main_window.preset_catalog.get_all_presets()
        for p in presets:
            item = QListWidgetItem(p.get('name', 'Без названия'))
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.preset_list.addItem(item)

    def _on_preset_selected(self):
        selected = self.preset_list.selectedItems()
        if not selected:
            return
        preset_data = selected[0].data(Qt.ItemDataRole.UserRole)

        self.lbl_name.setText(preset_data.get('name', '-'))
        self.lbl_category.setText(preset_data.get('category', 'Общая'))

        components = preset_data.get('components', [])
        self.lbl_components.setText(f"{len(components)} шт.")

        self.rack_list.clear()
        for comp in components:
            self.rack_list.addItem(f" [{comp.get('type', 'FX')}] {comp.get('name', 'Unknown')}")

    def _on_load_clicked(self):
        selected = self.preset_list.selectedItems()
        if not selected:
            return
        preset_data = selected[0].data(Qt.ItemDataRole.UserRole)
        preset_id = preset_data.get('id')

        self.main_window.log(f"Запрос на загрузку пресета: {preset_data.get('name')}", "info")
        success = self.main_window.plugin_service.switch_preset_by_id(preset_id)
        if success:
            self.main_window.log(
                f"Пресет {preset_data.get('name')} успешно загружен!", "success"
            )
            self.main_window.state_manager.update_state(current_preset=preset_data.get('name'))
        else:
            self.main_window.log(
                f"Не удалось загрузить пресет {preset_data.get('name')}", "error"
            )

    def _update_rack_chain(self):
        if not self.main_window.plugin_service:
            return
        if self.main_window.plugin_service.get_status().get('plugin_loaded'):
            current = self.main_window.plugin_service.get_current_preset_info()
            if current:
                self.lbl_name.setText(current.get('name', '-'))
                self.lbl_category.setText(current.get('category', 'Общая'))


class AudioPlayerTab(QWidget):
    """Вкладка медиаплеера фонограмм"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

        self.track_timer = QTimer()
        self.track_timer.setInterval(500)
        self.track_timer.timeout.connect(self._update_playback_progress)
        self.track_timer.start()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_box = QGroupBox("Плейлист минусовок (Backing Tracks)")
        left_layout = QVBoxLayout(left_box)
        self.track_list = QListWidget()
        self.track_list.itemDoubleClicked.connect(self._on_track_double_clicked)
        left_layout.addWidget(self.track_list)
        splitter.addWidget(left_box)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        control_box = QGroupBox("Управление воспроизведением")
        control_layout = QVBoxLayout(control_box)

        self.lbl_current_track = QLabel("Трек не выбран")
        self.lbl_current_track.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_current_track.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #FF9D00; padding: 10px;"
        )
        control_layout.addWidget(self.lbl_current_track)

        progress_layout = QHBoxLayout()
        self.lbl_time_cur = QLabel("00:00")
        self.slider_progress = QSlider(Qt.Orientation.Horizontal)
        self.slider_progress.sliderMoved.connect(self._on_slider_moved)
        self.lbl_time_total = QLabel("00:00")
        progress_layout.addWidget(self.lbl_time_cur)
        progress_layout.addWidget(self.slider_progress)
        progress_layout.addWidget(self.lbl_time_total)
        control_layout.addLayout(progress_layout)

        btn_layout = QHBoxLayout()
        self.btn_prev = QPushButton("⏮ Пред")
        self.btn_prev.clicked.connect(self._on_prev_clicked)
        self.btn_play = QPushButton("▶ ИГРАТЬ")
        self.btn_play.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.btn_play.clicked.connect(self._on_play_clicked)
        self.btn_pause = QPushButton("⏸ ПАУЗА")
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        self.btn_next = QPushButton("⏭ След")
        self.btn_next.clicked.connect(self._on_next_clicked)

        btn_layout.addWidget(self.btn_prev)
        btn_layout.addWidget(self.btn_play)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_next)
        control_layout.addLayout(btn_layout)

        vol_layout = QHBoxLayout()
        vol_layout.addWidget(QLabel("Громкость плеера:"))
        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(80)
        self.slider_volume.valueChanged.connect(self._on_volume_changed)
        vol_layout.addWidget(self.slider_volume)
        control_layout.addLayout(vol_layout)

        right_layout.addWidget(control_box)

        auto_box = QGroupBox("Автоматизация трека (Preset Sync)")
        auto_layout = QVBoxLayout(auto_box)
        auto_layout.addWidget(QLabel("Пресеты, привязанные к таймлайну трека:"))
        self.sync_list = QListWidget()
        auto_layout.addWidget(self.sync_list)

        sync_btn_layout = QHBoxLayout()
        sync_btn_layout.addWidget(QPushButton("Добавить маркер пресета"))
        sync_btn_layout.addWidget(QPushButton("Удалить маркер"))
        auto_layout.addLayout(sync_btn_layout)
        right_layout.addWidget(auto_box)

        splitter.addWidget(right_panel)
        splitter.setSizes([500, 700])
        layout.addWidget(splitter)

    def update_tracks(self):
        self.track_list.clear()
        tracks = self.main_window.player_service.get_playlist()
        for t in tracks:
            item = QListWidgetItem(t.get('name', 'Неизвестный трек'))
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.track_list.addItem(item)

    def _on_track_double_clicked(self, item):
        track_data = item.data(Qt.ItemDataRole.UserRole)
        self._play_track(track_data)

    def _play_track(self, track_data):
        if not track_data:
            return
        self.lbl_current_track.setText(track_data.get('name', 'Трек'))
        if self.main_window.player_service.play_track(track_data.get('id')):
            self.main_window.log(
                f"Воспроизведение трека: {track_data.get('name')}", "info"
            )

    def _on_play_clicked(self):
        status = self.main_window.player_service.get_status()
        if status.get('state') == 'paused':
            self.main_window.player_service.resume()
            self.main_window.log("Плеер возобновлен", "info")
            return

        current = self.main_window.player_service.get_current_track()
        if current:
            self.main_window.player_service.play_track(current.id)
            return

        if self.track_list.count() > 0:
            self._play_track(self.track_list.item(0).data(Qt.ItemDataRole.UserRole))

    def _on_pause_clicked(self):
        self.main_window.player_service.pause()
        self.main_window.log("Воспроизведение приостановлено", "info")

    def _on_prev_clicked(self):
        next_id = self.main_window.player_service.prev()
        if next_id:
            self.main_window.player_service.play_track(next_id)
            self._sync_ui_with_current_track()

    def _on_next_clicked(self):
        next_id = self.main_window.player_service.next()
        if next_id:
            self.main_window.player_service.play_track(next_id)
            self._sync_ui_with_current_track()

    def _on_volume_changed(self, value):
        self.main_window.player_service.set_volume(value / 100.0)

    def _on_slider_moved(self, value):
        self.main_window.player_service.set_position(value)

    def _sync_ui_with_current_track(self):
        current = self.main_window.player_service.get_current_track()
        if current:
            self.lbl_current_track.setText(current.name)

    def _update_playback_progress(self):
        status = self.main_window.player_service.get_status()
        if not isinstance(status, dict):
            return

        self.slider_progress.setRange(0, int(status.get('duration', 1)))
        self.slider_progress.setValue(int(status.get('position', 0)))
        self.lbl_time_cur.setText(self._format_time(status.get('position', 0)))
        self.lbl_time_total.setText(self._format_time(status.get('duration', 0)))

    def _format_time(self, seconds):
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{mins:02d}:{secs:02d}"


class SettingsTab(QWidget):
    """Вкладка настроек аудио, MIDI и сервера"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        grid = QGridLayout()

        audio_box = QGroupBox("Настройки звукового движка ASIO")
        audio_layout = QVBoxLayout(audio_box)

        audio_layout.addWidget(QLabel("ASIO Драйвер:"))
        self.combo_asio = QComboBox()
        self.combo_asio.addItems([
            "ASIO4ALL v2", "FL Studio ASIO", "Focusrite USB ASIO", "Behringer USB ASIO"
        ])
        audio_layout.addWidget(self.combo_asio)

        audio_layout.addWidget(QLabel("Размер буфера (Latency):"))
        self.combo_buffer = QComboBox()
        self.combo_buffer.addItems(["64 samples", "128 samples", "256 samples", "512 samples"])
        self.combo_buffer.setCurrentIndex(2)
        audio_layout.addWidget(self.combo_buffer)

        self.btn_restart_audio = QPushButton("Перезапустить аудио движок")
        self.btn_restart_audio.clicked.connect(self._restart_audio)
        audio_layout.addWidget(self.btn_restart_audio)
        grid.addWidget(audio_box, 0, 0)

        midi_box = QGroupBox("Параметры MIDI контроллера")
        midi_layout = QVBoxLayout(midi_box)

        midi_layout.addWidget(QLabel("Входной MIDI порт:"))
        self.combo_midi_in = QComboBox()
        self.combo_midi_in.addItems([
            "Arduino USB MIDI", "LoopMIDI Port 1", "Компьютерный MIDI вход"
        ])
        midi_layout.addWidget(self.combo_midi_in)

        midi_layout.addWidget(QLabel("Режим обработки педали:"))
        self.combo_midi_mode = QComboBox()
        self.combo_midi_mode.addItems([
            "Прямой переключатель (Stomp)",
            "Банковый режим (Banks)",
            "Студийный пресет-матрица"
        ])
        midi_layout.addWidget(self.combo_midi_mode)
        grid.addWidget(midi_box, 0, 1)

        com_box = QGroupBox("Подключение ножного контроллера")
        com_layout = QVBoxLayout(com_box)

        com_layout.addWidget(QLabel("Последовательный COM-порт:"))
        self.combo_com = QComboBox()
        self.combo_com.addItems(["COM1", "COM3", "COM5 (Bluetooth HC-05)", "COM6"])
        com_layout.addWidget(self.combo_com)

        self.btn_connect_com = QPushButton("Установить соединение")
        self.btn_connect_com.clicked.connect(self._connect_com)
        com_layout.addWidget(self.btn_connect_com)
        grid.addWidget(com_box, 1, 0)

        web_box = QGroupBox("Сервер мобильного приложения")
        web_layout = QVBoxLayout(web_box)

        self.lbl_server_ip = QLabel("Локальный адрес сервера: http://192.168.1.50:5000")
        self.lbl_server_ip.setStyleSheet("color: #FF9D00; font-weight: bold;")
        web_layout.addWidget(self.lbl_server_ip)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(120, 120)
        web_layout.addWidget(self.qr_label)
        grid.addWidget(web_box, 1, 1)

        layout.addLayout(grid)

        perf_box = QGroupBox("Performance & DSP Монитор")
        perf_layout = QHBoxLayout(perf_box)
        perf_layout.addWidget(QLabel("Загрузка DSP:"))
        self.dsp_progress = QProgressBar()
        self.dsp_progress.setValue(14)
        self.dsp_progress.setStyleSheet("QProgressBar::chunk { background-color: #FF9D00; }")
        perf_layout.addWidget(self.dsp_progress)
        layout.addWidget(perf_box)

        self.generate_qr()

    def generate_qr(self):
        try:
            qr_pixmap = QRGenerator.generate_room_qr(
                "http://192.168.1.50:5000", "GR7_SECURE_AUTH"
            )
            if qr_pixmap and not qr_pixmap.isNull():
                self.qr_label.setPixmap(qr_pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio))
            else:
                self.qr_label.setText("[ QR код недоступен ]")
        except Exception as e:
            self.qr_label.setText("[ Ошибка QR ]")
            self.main_window.log(f"Ошибка генерации QR: {e}", "error")

    def _restart_audio(self):
        driver = self.combo_asio.currentText()
        result = self.main_window.audio_service.configure_device(driver)
        if result:
            self.main_window.log(f"Перезапуск аудио драйвера {driver} выполнен", "info")
        else:
            self.main_window.log(
                f"Изменение ASIO драйвера {driver} не поддерживается текущим движком", "warning"
            )

    def _connect_com(self):
        self.main_window.log("Попытка установить соединение с COM-портом...", "info")
        self.main_window.log("Реальное подключение COM-порта не реализовано в текущей версии", "warning")


class MIDITab(QWidget):
    """Вкладка управления MIDI"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        status_box = QGroupBox("Статус MIDI")
        status_layout = QVBoxLayout(status_box)
        self.midi_status = QLabel("MIDI: не инициализирован")
        status_layout.addWidget(self.midi_status)

        self.btn_refresh = QPushButton("Обновить статус MIDI")
        self.btn_refresh.clicked.connect(self.update_status)
        status_layout.addWidget(self.btn_refresh)

        self.btn_send_pc = QPushButton("Отправить Program Change")
        self.btn_send_pc.clicked.connect(self._send_program_change)
        status_layout.addWidget(self.btn_send_pc)

        layout.addWidget(status_box)
        layout.addStretch()

    def update_status(self):
        status = self.main_window.midi_service.get_status()
        if status.get('initialized'):
            port_active = status.get('port_active', False)
            text = "MIDI: активен" if port_active else "MIDI: инициализирован, порт не активен"
        else:
            text = "MIDI: не инициализирован"
        self.midi_status.setText(text)

    def _send_program_change(self):
        if self.main_window.midi_service.send_program_change(0):
            self.main_window.log("MIDI Program Change отправлен", "info")
        else:
            self.main_window.log("Ошибка отправки MIDI Program Change", "error")


class NetworkTab(QWidget):
    """Вкладка состояния сети и API"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.server_status = QLabel("API сервер: остановлен")
        layout.addWidget(self.server_status)

        self.btn_restart_server = QPushButton("Перезапустить API сервер")
        self.btn_restart_server.clicked.connect(self._restart_api_server)
        layout.addWidget(self.btn_restart_server)

        self.btn_show_port = QPushButton("Показать порт API")
        self.btn_show_port.clicked.connect(self._show_api_port)
        layout.addWidget(self.btn_show_port)

        layout.addStretch()

    def update_status(self):
        if self.main_window.api_server.is_running():
            self.server_status.setText(
                f"API сервер запущен на порту {self.main_window.api_server.get_port()}"
            )
        else:
            self.server_status.setText("API сервер: остановлен")

    def _restart_api_server(self):
        success = self.main_window.api_server.start()
        if success:
            self.main_window.log("API сервер запущен", "info")
        else:
            self.main_window.log("Не удалось запустить API сервер", "error")
        self.update_status()

    def _show_api_port(self):
        port = self.main_window.api_server.get_port()
        self.main_window.log(f"API порт: {port}", "info")
        self.server_status.setText(f"API сервер порт: {port}")


class LogsTab(QWidget):
    """Вкладка системных логов"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        layout.addWidget(self.log_widget)

    def append_message(self, formatted_msg: str):
        self.log_widget.append(formatted_msg)
        self.log_widget.moveCursor(QTextCursor.MoveOperation.End)


class WebRTCTab(QWidget):
    """Вкладка WebRTC и транспорта"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Мониторинг WebRTC и состояния транспорта"))

        webrtc_box = QGroupBox("Статус аудиостриминга WebRTC")
        webrtc_layout = QVBoxLayout(webrtc_box)
        self.webrtc_status = QLabel("Поток остановлен. Комната ожидания: не создана")
        webrtc_layout.addWidget(self.webrtc_status)
        layout.addWidget(webrtc_box)
        layout.addStretch()

    def update_transport(self):
        status = self.main_window.webrtc_service.get_status()
        if status.get('initialized'):
            room_id = status.get('room_id') or 'не создана'
            self.webrtc_status.setText(f"WebRTC: подключено, комната: {room_id}")
        else:
            self.webrtc_status.setText("WebRTC: остановлено или не инициализировано")


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self):
        super().__init__()
        self.gui_signals = GUISignals()
        self.gui_signals.log_signal.connect(self.log_widget_safe_append)

        self.setWindowTitle("GR7 Hub - Пульт управления Guitar Rig 7")
        self.setGeometry(100, 100, 1200, 800)

        self.config_loader = ConfigLoader()
        self.state_manager = StateManager()
        self.logger = Logger("MainWindow")

        self.plugin_service = PluginService(
            self.config_loader, self.state_manager, self.logger
        )
        self.audio_service = AudioService(
            self.config_loader, self.state_manager, self.logger
        )
        self.midi_service = MIDIService(
            self.config_loader, self.state_manager, self.logger
        )
        self.webrtc_service = WebRTCService(
            self.config_loader, self.state_manager, self.logger
        )
        self.player_service = PlayerService(self.config_loader, self.logger)
        self.preset_catalog = PresetCatalog(self.config_loader, self.logger)

        self.api_server = APIServer(
            self.config_loader,
            self.logger,
            self.preset_catalog,
            player_service=self.player_service,
            plugin_service=self.plugin_service
        )

        self.init_ui()

        threading.Thread(target=self._init_services, daemon=True).start()
        QTimer.singleShot(300, self._init_vst_safe)

        self.ui_timer = QTimer()
        self.ui_timer.setInterval(100)
        self.ui_timer.timeout.connect(self._update_status)
        self.ui_timer.start()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

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

        self.system_status = QLabel("Запуск системных подсистем...")
        self.system_status.setStyleSheet("color: #888888; font-size: 11px;")
        header_layout.addWidget(self.system_status)
        main_layout.addWidget(header_frame)

        self.tabs = QTabWidget()
        self.preset_browser_tab = PresetBrowserTab(self)
        self.audio_player_tab = AudioPlayerTab(self)
        self.midi_tab = MIDITab(self)
        self.webrtc_tab = WebRTCTab(self)
        self.network_tab = NetworkTab(self)
        self.settings_tab = SettingsTab(self)
        self.logs_tab = LogsTab(self)

        self.tabs.addTab(self.preset_browser_tab, "Пресеты")
        self.tabs.addTab(self.audio_player_tab, "Плеер")
        self.tabs.addTab(self.midi_tab, "MIDI")
        self.tabs.addTab(self.webrtc_tab, "WebRTC")
        self.tabs.addTab(self.network_tab, "Сеть")
        self.tabs.addTab(self.settings_tab, "Настройки")
        self.tabs.addTab(self.logs_tab, "Логи")

        main_layout.addWidget(self.tabs)

    def _init_services(self):
        try:
            self.logger.log("[BOOT] PresetCatalog init start", "info")
            if self.preset_catalog.initialize():
                self.logger.log("[BOOT] PresetCatalog init complete", "info")
                QTimer.singleShot(0, self.preset_browser_tab.update_presets)
            else:
                self.logger.log("[BOOT] PresetCatalog init failed", "error")

            self.logger.log("[BOOT] PlayerService init start", "info")
            if self.player_service.initialize():
                self.logger.log("[BOOT] PlayerService init complete", "info")
                QTimer.singleShot(0, self.audio_player_tab.update_tracks)
            else:
                self.logger.log("[BOOT] PlayerService init failed", "error")

            self.logger.log("[BOOT] API Server init start", "info")
            if self.api_server.start():
                self.logger.log("[BOOT] API Server запущен", "info")
            else:
                self.logger.log("[BOOT] API Server запуск провален", "error")

            self.logger.log("[BOOT] Фоновые службы инициализированы", "success")
        except Exception as e:
            self.logger.log(f"[BOOT] Ошибка фоновой инициализации служб: {e}", "error")

    def _init_vst_safe(self):
        try:
            self.logger.log("[BOOT] VST3 init start", "info")
            if self.plugin_service.initialize():
                self.logger.log("[BOOT] VST3 подгружен успешно", "info")
            else:
                self.logger.log("[BOOT] VST3 не указан в config.ini или не найден.", "warning")
        except Exception as e:
            self.logger.log(f"[BOOT] Ошибка инициализации VST3: {e}", "error")

    def _update_status(self):
        try:
            self.preset_browser_tab._update_rack_chain()
            self.midi_tab.update_status()
            self.webrtc_tab.update_transport()
            self.network_tab.update_status()
        except Exception as e:
            self.logger.log(f"Ошибка таймера обновления вкладок: {e}", "error")

        try:
            state = self.state_manager.state.get_state_dict()
        except Exception:
            state = {}

        status_text = (
            f"VST3: {'OK' if state.get('plugin_loaded') else 'NO'} | "
            f"Audio: {'OK' if state.get('audio_engine_active') else 'NO'} | "
            f"MIDI: {'OK' if state.get('midi_active') else 'NO'} | "
            f"WebRTC: {'OK' if state.get('webrtc_active') else 'NO'} | "
            f"API: {'OK' if self.api_server.is_running() else 'NO'}"
        )
        self.system_status.setText(status_text)

    def log(self, message: str, level: str = "info"):
        self.logger.log(message, level)
        self.gui_signals.log_signal.emit(message, level)

    def log_widget_safe_append(self, message: str, level: str):
        color = "#A0A0A0"
        if level == "error":
            color = "#FF3333"
        elif level == "success":
            color = "#33FF33"
        elif level == "warning":
            color = "#FF9D00"

        formatted_msg = f"<span style='color:{color};'>[{level.upper()}] {message}</span>"
        if hasattr(self, 'logs_tab') and self.logs_tab is not None:
            self.logs_tab.append_message(formatted_msg)

    def closeEvent(self, event):
        try:
            self.api_server.stop()
            self.plugin_service.shutdown()
            self.audio_service.shutdown()
            self.midi_service.shutdown()
            self.webrtc_service.shutdown()
            self.player_service.shutdown()
        except Exception:
            pass
        event.accept()
