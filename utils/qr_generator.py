"""
QRGenerator
==========
Генерация QR кодов для WebRTC комнат.
Thread-safe, async, без блокировок GUI.
Уникальные QR для каждой сессии.
"""

import qrcode
import json
import threading
import uuid
import secrets
import time
from typing import Optional, Tuple
from pathlib import Path
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QObject, pyqtSignal, QThread


class QRWorker(QThread):
    """Фоновый worker для генерации QR"""
    
    finished = pyqtSignal(object, str)  # (QPixmap, session_id)
    error = pyqtSignal(str)
    
    def __init__(self, room_url: str, auth_token: Optional[str] = None):
        super().__init__()
        self.room_url = room_url
        self.auth_token = auth_token
        self._stop_event = threading.Event()
    
    def run(self):
        """Генерация QR в фоне"""
        try:
            # Создаем уникальные данные для сессии
            session_id = str(uuid.uuid4())
            nonce = secrets.token_hex(16)
            pairing_code = secrets.token_urlsafe(16)
            
            # Данные для QR
            qr_data = {
                "type": "gr7_room",
                "session_id": session_id,
                "nonce": nonce,
                "pairing_code": pairing_code,
                "url": self.room_url,
                "timestamp": int(time.time())
            }
            if self.auth_token:
                qr_data["token"] = self.auth_token
            
            # Генерация QR
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(json.dumps(qr_data))
            qr.make(fit=True)
            
            # Создание изображения
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Конвертация в QPixmap
            import io
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            
            self.finished.emit(pixmap, session_id)
            
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self._stop_event.set()
    
    def stop(self):
        """Остановка worker"""
        self._stop_event.set()
        self.wait()


class QRGenerator:
    """Генератор QR кодов (thread-safe, async)"""
    
    _lock = threading.Lock()
    _output_dir: Optional[Path] = None
    _current_session_id: Optional[str] = None
    _current_worker: Optional[QRWorker] = None
    
    @classmethod
    def initialize(cls, output_dir: str = ".qr_cache"):
        """Инициализация генератора QR."""
        with cls._lock:
            cls._output_dir = Path(output_dir)
            cls._output_dir.mkdir(exist_ok=True)
    
    @classmethod
    def start_new_session(cls, room_id: Optional[str] = None) -> str:
        """
        Создание новой сессии с уникальным QR.
        
        Args:
            room_id: Опциональный room_id
            
        Returns:
            str: session_id
        """
        with cls._lock:
            # Генерируем уникальный session_id
            session_id = room_id or str(uuid.uuid4())
            cls._current_session_id = session_id
            
            # Очищаем старый worker
            if cls._current_worker:
                cls._current_worker.stop()
                cls._current_worker = None
            
            return session_id
    
    @classmethod
    def generate_room_qr(cls, room_url: str, auth_token: Optional[str] = None) -> Tuple[Optional[QPixmap], Optional[str]]:
        """
        Генерация QR кода для текущей сессии (async).
        
        Args:
            room_url: URL комнаты
            auth_token: Опциональный токен аутентификации
            
        Returns:
            Tuple[QPixmap, session_id] или (None, error)
        """
        with cls._lock:
            # Инициализируем при необходимости
            if cls._output_dir is None:
                cls.initialize()
            
            # Создаем worker
            worker = QRWorker(room_url, auth_token)
            cls._current_worker = worker
            
            # Запускаем в фоне
            worker.start()
            
            return None, "Generating..."
    
    @classmethod
    def get_current_session_id(cls) -> Optional[str]:
        """Получение текущего session_id."""
        with cls._lock:
            return cls._current_session_id
    
    @classmethod
    def get_output_dir(cls) -> Path:
        """Получение директории вывода."""
        with cls._lock:
            if cls._output_dir is None:
                cls.initialize()
            return cls._output_dir