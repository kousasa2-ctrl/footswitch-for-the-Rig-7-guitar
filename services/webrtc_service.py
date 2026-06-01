"""
WebRTCService
==============
Сервис управления WebRTC соединением.
"""

import threading
import traceback
from typing import Optional, Dict, Any, Callable
from webrtc.stream import WebRTCStream
from core.state_manager import StateManager
from core.logger import Logger


class WebRTCService:
    """Сервис управления WebRTC"""

    def __init__(self, config, state_manager: StateManager, logger: Logger):
        self.config = config
        self.state_manager = state_manager
        self.logger = logger
        self.stream: Optional[WebRTCStream] = None
        self._initialized = False
        self._room_id: Optional[str] = None
        self._connection_callback: Optional[Callable] = None
        self._lock = threading.Lock()

    def initialize(self) -> bool:
        """
        Инициализация сервиса.

        Returns:
            bool: True если успешно
        """
        try:
            self.stream = WebRTCStream(self.config, self.logger)

            if not self.stream.initialize():
                self.state_manager.update_state(webrtc_active=False)
                if self.logger:
                    self.logger.log_webrtc("WebRTC поток не инициализирован", "error")
                return False

            self._initialized = True
            self.state_manager.update_state(webrtc_active=True)
            if self.logger:
                self.logger.log_webrtc("WebRTC поток инициализирован", "info")

            return True

        except Exception as e:
            self.state_manager.update_state(webrtc_active=False)
            if self.logger:
                self.logger.log_webrtc(f"Ошибка инициализации: {e}", "error")
                self.logger.log_webrtc(traceback.format_exc(), "error")
            return False

    def create_room(self) -> str:
        """
        Создание комнаты.

        Returns:
            str: ID комнаты
        """
        try:
            if not self._initialized or not self.stream:
                if self.logger:
                    self.logger.log_webrtc("WebRTC не инициализирован", "error")
                return ""

            self._room_id = self.stream.signaling.create_room()
            if self._room_id:
                if self.logger:
                    self.logger.log_webrtc(f"Комната создана: {self._room_id}", "info")
            return self._room_id
        except Exception as e:
            if self.logger:
                self.logger.log_webrtc(f"Ошибка создания комнаты: {e}", "error")
                self.logger.log_webrtc(traceback.format_exc(), "error")
            return ""

    def get_room_id(self) -> Optional[str]:
        """Получение ID текущей комнаты"""
        return self._room_id

    def set_connection_callback(self, callback: Callable) -> None:
        """
        Установка callback для изменений соединения.

        Args:
            callback: Функция callback(connected: bool)
        """
        self._connection_callback = callback

    def notify_connection_change(self, connected: bool) -> None:
        """Уведомление о изменении соединения"""
        if self._connection_callback:
            try:
                self._connection_callback(connected)
            except Exception as e:
                if self.logger:
                    self.logger.log_webrtc(f"Ошибка callback: {e}", "error")

    def get_status(self) -> dict:
        """Получение статуса"""
        try:
            if self.stream:
                status = self.stream.get_status()
                status['initialized'] = self._initialized
                status['room_id'] = self._room_id
                return status
            return {'initialized': False, 'running': False, 'room_id': None}
        except Exception:
            return {'initialized': False, 'running': False, 'room_id': None}

    def shutdown(self) -> None:
        """Остановка сервиса"""
        try:
            if self.stream:
                self.stream.shutdown()
                self.stream = None
            self._initialized = False
            self._room_id = None
            if self.logger:
                self.logger.log_webrtc("WebRTCService остановлен", "info")
        except Exception:
            pass