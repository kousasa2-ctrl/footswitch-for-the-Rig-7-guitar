"""
QRGenerator
===========
Генерация QR кодов для WebRTC комнат.
Thread-safe и с поддержкой PyQt.
"""

import qrcode
import json
import threading
from typing import Optional
from pathlib import Path
from PyQt6.QtGui import QPixmap


class QRGenerator:
    """Генератор QR кодов (thread-safe)"""

    _lock = threading.Lock()
    _output_dir: Optional[Path] = None
    _cache: dict = {}

    @classmethod
    def initialize(cls, output_dir: str = ".qr_cache"):
        """Инициализация генератора QR."""
        with cls._lock:
            cls._output_dir = Path(output_dir)
            cls._output_dir.mkdir(exist_ok=True)

    @classmethod
    def generate_room_qr(cls, room_url: str, auth_token: Optional[str] = None) -> Optional[QPixmap]:
        """
        Генерация QR кода для комнаты.

        Args:
            room_url: URL комнаты
            auth_token: Опциональный токен аутентификации

        Returns:
            Optional[QPixmap]: QPixmap для отображения в GUI или None при ошибке
        """
        with cls._lock:
            # Инициализируем при необходимости
            if cls._output_dir is None:
                cls.initialize()

            try:
                # QR содержит информацию о комнате
                qr_data = {
                    "type": "gr7_room",
                    "url": room_url
                }
                if auth_token:
                    qr_data["token"] = auth_token

                cache_key = json.dumps(qr_data, sort_keys=True)

                # Проверяем кэш
                if cache_key in cls._cache:
                    return cls._cache[cache_key]

                # Создание QR
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(json.dumps(qr_data))
                qr.make(fit=True)

                # Создание изображения PIL
                img = qr.make_image(fill_color="black", back_color="white")

                # Конвертация в QPixmap
                import io
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                buffer.seek(0)

                pixmap = QPixmap()
                pixmap.loadFromData(buffer.getvalue())

                # Кэшируем результат
                cls._cache[cache_key] = pixmap

                # Опционально сохраняем файл
                filename = f"gr7_qr_{abs(hash(cache_key)) % 1000000}.png"
                filepath = cls._output_dir / filename
                img.save(str(filepath))

                return pixmap

            except Exception as e:
                print(f"[QR] Ошибка генерации QR: {e}")
                import traceback
                traceback.print_exc()
                return None

    @classmethod
    def clear_cache(cls):
        """Очистка кэша QR кодов."""
        with cls._lock:
            cls._cache.clear()

    @classmethod
    def get_output_dir(cls) -> Path:
        """Получение директории вывода."""
        with cls._lock:
            if cls._output_dir is None:
                cls.initialize()
            return cls._output_dir