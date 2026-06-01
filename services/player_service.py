"""
PlayerService
==============
Сервис управления backing track player.
"""

import os
import threading
import time
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import queue
import json


class PlayerState(Enum):
    """Состояния плеера"""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class TrackInfo:
    """Информация о треке"""
    id: str
    name: str
    path: str
    duration: float = 0.0
    size_bytes: int = 0
    format: str = "mp3"
    is_playing: bool = False
    volume: float = 1.0
    position: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'id': self.id,
            'name': self.name,
            'path': self.path,
            'duration': self.duration,
            'size_bytes': self.size_bytes,
            'format': self.format,
            'is_playing': self.is_playing,
            'volume': self.volume,
            'position': self.position
        }


class PlayerService:
    """Сервис управления backing track player"""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self._lock = threading.Lock()
        self._tracks: Dict[str, TrackInfo] = {}
        self._current_track_id: Optional[str] = None
        self._state: PlayerState = PlayerState.STOPPED
        self._volume: float = 1.0
        self._position: float = 0.0
        self._duration: float = 0.0
        self._playback_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._position_queue = queue.Queue()
        self._track_queue = queue.Queue()
        self._volume_queue = queue.Queue()
        self._callback: Optional[Callable] = None
        self._audio_device = None
        self._sample_rate = 44100
        self._buffer_size = 256

    def initialize(self) -> bool:
        """
        Инициализация плеера.

        Returns:
            bool: True если успешно
        """
        try:
            # Получаем настройки из конфигурации
            self._sample_rate = int(self.config.get('audio', 'sample_rate', '44100'))
            self._buffer_size = int(self.config.get('audio', 'buffer_size', '256'))

            # Получаем путь к трекам
            songs_folder = self.config.get('gr7', 'songs', '')
            if not songs_folder:
                songs_folder = self.config.get('paths', 'songs', '')

            if songs_folder:
                self._load_tracks(songs_folder)
            else:
                if self.logger:
                    self.logger.log_player("Папка с треками не указана", "warning")

            if self.logger:
                self.logger.log_player(f"PlayerService инициализирован, треков: {len(self._tracks)}", "info")

            return True

        except Exception as e:
            if self.logger:
                self.logger.log_player(f"Ошибка инициализации: {e}", "error")
                self.logger.log_player(traceback.format_exc(), "error")
            return False

    def _load_tracks(self, folder: str) -> None:
        """Загрузка треков из папки"""
        try:
            folder_path = Path(folder)

            if not folder_path.exists():
                if self.logger:
                    self.logger.log_player(f"Папка не существует: {folder_path}", "error")
                return

            # Поддерживаемые форматы
            supported_formats = ['.mp3', '.wav', '.flac', '.ogg', '.m4a']

            # Ищем файлы
            for ext in supported_formats:
                for file_path in folder_path.rglob(f"*{ext}"):
                    self._add_track(file_path)

            if self.logger:
                self.logger.log_player(f"Загружено треков: {len(self._tracks)}", "info")

        except Exception as e:
            if self.logger:
                self.logger.log_player(f"Ошибка загрузки треков: {e}", "error")
                self.logger.log_player(traceback.format_exc(), "error")

    def _add_track(self, file_path: Path) -> None:
        """Добавление трека"""
        try:
            # Создаем ID трека
            track_id = f"track_{file_path.stem}"

            # Проверяем, есть ли уже такой трек
            if track_id in self._tracks:
                return

            # Получаем размер файла
            size_bytes = file_path.stat().st_size

            # Определяем формат
            ext = file_path.suffix.lower()
            format_map = {
                '.mp3': 'mp3',
                '.wav': 'wav',
                '.flac': 'flac',
                '.ogg': 'ogg',
                '.m4a': 'm4a'
            }
            file_format = format_map.get(ext, 'unknown')

            # Создаем информацию о треке
            track_info = TrackInfo(
                id=track_id,
                name=file_path.stem,
                path=str(file_path),
                size_bytes=size_bytes,
                format=file_format
            )

            # Добавляем в список
            with self._lock:
                self._tracks[track_id] = track_info

            if self.logger:
                self.logger.log_player(f"Добавлен трек: {track_id}", "debug")

        except Exception as e:
            if self.logger:
                self.logger.log_player(f"Ошибка добавления трека {file_path}: {e}", "error")

    def get_track(self, track_id: str) -> Optional[TrackInfo]:
        """Получение информации о треке"""
        try:
            with self._lock:
                return self._tracks.get(track_id)
        except Exception:
            return None

    def get_all_tracks(self) -> List[TrackInfo]:
        """Получение списка всех треков"""
        try:
            with self._lock:
                return list(self._tracks.values())
        except Exception:
            return []

    def get_track_list(self, search_query: Optional[str] = None,
                       limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Получение списка треков (API для мобильного клиента).

        Args:
            search_query: Поисковый запрос
            limit: Лимит результатов

        Returns:
            Dict: Список треков с метаданными
        """
        try:
            with self._lock:
                tracks = list(self._tracks.values())

                if search_query:
                    query = search_query.lower()
                    tracks = [t for t in tracks if query in t.name.lower()]

                if limit:
                    tracks = tracks[:limit]

                result = {
                    'total': len(self._tracks),
                    'tracks': [t.to_dict() for t in tracks]
                }

                return result
        except Exception as e:
            if self.logger:
                self.logger.log_player(f"Ошибка получения списка треков: {e}", "error")
            return {'total': 0, 'tracks': []}

    def play_track(self, track_id: str) -> bool:
        """
        Воспроизведение трека.

        Args:
            track_id: ID трека

        Returns:
            bool: True если успешно
        """
        try:
            with self._lock:
                if track_id not in self._tracks:
                    if self.logger:
                        self.logger.log_player(f"Трек не найден: {track_id}", "error")
                    return False

                # Останавливаем текущий трек
                self._stop()

                track = self._tracks[track_id]
                self._current_track_id = track_id
                self._position = 0.0
                self._duration = track.duration if track.duration > 0 else 1.0

                self._state = PlayerState.PLAYING
                self._stop_event.clear()
                self._track_queue.put(track_id)

                if not self._playback_thread or not self._playback_thread.is_alive():
                    self._playback_thread = threading.Thread(
                        target=self._playback_loop,
                        daemon=True
                    )
                    self._playback_thread.start()

                if self.logger:
                    self.logger.log_player(f"Воспроизведение: {track_id}", "info")

                return True
        except Exception as e:
            if self.logger:
                self.logger.log_player(f"Ошибка воспроизведения: {e}", "error")
                self.logger.log_player(traceback.format_exc(), "error")
            return False

    def stop(self) -> None:
        """Остановка воспроизведения"""
        try:
            self._stop()
        except Exception as e:
            if self.logger:
                self.logger.log_player(f"Ошибка остановки: {e}", "error")

    def _stop(self) -> None:
        """Внутренняя остановка"""
        try:
            with self._lock:
                self._state = PlayerState.STOPPED
                self._stop_event.set()
                self._position = 0.0
                self._duration = 0.0

                if self._playback_thread:
                    self._playback_thread.join(timeout=1.0)
                    self._playback_thread = None

                if self.logger:
                    self.logger.log_player("Воспроизведение остановлено", "info")
        except Exception:
            pass

    def pause(self) -> None:
        """Пауза"""
        try:
            with self._lock:
                if self._state == PlayerState.PLAYING:
                    self._state = PlayerState.PAUSED
                    if self.logger:
                        self.logger.log_player("Пауза", "info")
        except Exception:
            pass

    def resume(self) -> None:
        """Продолжение"""
        try:
            with self._lock:
                if self._state == PlayerState.PAUSED:
                    self._state = PlayerState.PLAYING
                    self._stop_event.clear()
                    if self.logger:
                        self.logger.log_player("Продолжение", "info")
        except Exception:
            pass

    def set_volume(self, volume: float) -> None:
        """
        Установка громкости.

        Args:
            volume: Громкость (0.0 - 1.0)
        """
        try:
            with self._lock:
                self._volume = max(0.0, min(1.0, volume))
                if self.logger:
                    self.logger.log_player(f"Громкость: {self._volume:.2f}", "debug")
        except Exception:
            pass

    def get_volume(self) -> float:
        """Получение громкости"""
        try:
            with self._lock:
                return self._volume
        except Exception:
            return 1.0

    def seek(self, position: float) -> None:
        """
        Перемотка.

        Args:
            position: Позиция в секундах
        """
        try:
            with self._lock:
                self._position = max(0.0, min(position, self._duration))
                if self.logger:
                    self.logger.log_player(f"Перемотка: {self._position:.1f}s", "debug")
        except Exception:
            pass

    def next_track(self) -> Optional[str]:
        """Следующий трек"""
        try:
            with self._lock:
                tracks = list(self._tracks.values())
                if not tracks:
                    return None

                if self._current_track_id:
                    try:
                        current_idx = next(i for i, t in enumerate(tracks) if t.id == self._current_track_id)
                        next_idx = (current_idx + 1) % len(tracks)
                        return tracks[next_idx].id
                    except (StopIteration, ValueError):
                        pass

                return tracks[0].id
        except Exception:
            return None

    def prev_track(self) -> Optional[str]:
        """Предыдущий трек"""
        try:
            with self._lock:
                tracks = list(self._tracks.values())
                if not tracks:
                    return None

                if self._current_track_id:
                    try:
                        current_idx = next(i for i, t in enumerate(tracks) if t.id == self._current_track_id)
                        prev_idx = (current_idx - 1) % len(tracks)
                        return tracks[prev_idx].id
                    except (StopIteration, ValueError):
                        pass

                return tracks[-1].id
        except Exception:
            return None

    def get_current_track(self) -> Optional[TrackInfo]:
        """Получение текущего трека"""
        try:
            with self._lock:
                if self._current_track_id:
                    return self._tracks.get(self._current_track_id)
                return None
        except Exception:
            return None

    def get_state(self) -> Dict[str, Any]:
        """Получение состояния плеера"""
        try:
            with self._lock:
                current_track = self.get_current_track()
                return {
                    'state': self._state.value,
                    'current_track': current_track.to_dict() if current_track else None,
                    'volume': self._volume,
                    'position': self._position,
                    'duration': self._duration,
                    'total_tracks': len(self._tracks)
                }
        except Exception:
            return {
                'state': 'stopped',
                'current_track': None,
                'volume': 1.0,
                'position': 0.0,
                'duration': 0.0,
                'total_tracks': 0
            }

    def get_playlist(self) -> List[Dict[str, Any]]:
        """Список треков для UI"""
        return [t.to_dict() for t in self.get_all_tracks()]

    def load_track(self, track_id: str) -> bool:
        """Загрузка трека для воспроизведения"""
        return self.play_track(track_id)

    def play(self) -> bool:
        """Запуск или возобновление воспроизведения"""
        if self._state == PlayerState.PAUSED:
            self.resume()
            return True

        current = self.get_current_track()
        if current:
            return self.play_track(current.id)
        return False

    def prev(self) -> Optional[str]:
        """Переход к предыдущему треку"""
        prev_id = self.prev_track()
        if prev_id:
            self.play_track(prev_id)
        return prev_id

    def next(self) -> Optional[str]:
        """Переход к следующему треку"""
        next_id = self.next_track()
        if next_id:
            self.play_track(next_id)
        return next_id

    def get_status(self) -> Dict[str, Any]:
        """Статус для совместимости API"""
        return self.get_state()

    def set_position(self, value: float) -> None:
        """Установка позиции воспроизведения"""
        self.seek(value)

    def _playback_loop(self) -> None:
        """Цикл воспроизведения"""
        while not self._stop_event.is_set():
            try:
                # Получаем трек из очереди
                track_id = self._track_queue.get(timeout=0.1)
                if track_id not in self._tracks:
                    continue

                track = self._tracks[track_id]
                self._current_track_id = track_id
                self._position = 0.0
                self._duration = track.duration if track.duration > 0 else 1.0

                while not self._stop_event.is_set() and self._position < self._duration:
                    time.sleep(0.1)
                    if self._state == PlayerState.PAUSED:
                        continue
                    self._position += 0.1

                # Трек закончился
                if not self._stop_event.is_set():
                    # Автоплей следующего
                    next_id = self.next_track()
                    if next_id:
                        self._track_queue.put(next_id)

            except queue.Empty:
                continue
            except Exception as e:
                if self.logger:
                    self.logger.log_player(f"Ошибка в playback loop: {e}", "error")
                    self.logger.log_player(traceback.format_exc(), "error")
                break

    def set_callback(self, callback: Callable) -> None:
        """
        Установка callback для обновлений.

        Args:
            callback: Функция callback(state)
        """
        self._callback = callback

    def _notify_callback(self) -> None:
        """Уведомление callback"""
        if self._callback:
            try:
                self._callback(self.get_state())
            except Exception as e:
                if self.logger:
                    self.logger.log_player(f"Ошибка callback: {e}", "error")

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики плеера"""
        try:
            with self._lock:
                return {
                    'total_tracks': len(self._tracks),
                    'current_track': self._current_track_id,
                    'state': self._state.value,
                    'volume': self._volume
                }
        except Exception:
            return {
                'total_tracks': 0,
                'current_track': None,
                'state': 'stopped',
                'volume': 1.0
            }

    def shutdown(self) -> None:
        """Остановка плеера"""
        try:
            self._stop()
            if self.logger:
                self.logger.log_player("PlayerService остановлен", "info")
        except Exception:
            pass