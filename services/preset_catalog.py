"""
PresetCatalog
=============
Серверный каталог пресетов Guitar Rig 7.
"""

import os
import json
import threading
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterator
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum


class PresetCategory(Enum):
    """Категории пресетов"""
    FACTORY = "factory"
    USER = "user"
    FAVORITES = "favorites"
    RECENT = "recent"
    SEARCH = "search"


@dataclass
class PresetInfo:
    """Информация о пресете"""
    id: str
    name: str
    category: PresetCategory
    path: str
    rack_chain: List[Dict[str, Any]] = field(default_factory=list)
    parameters: Dict[str, float] = field(default_factory=dict)
    is_favorite: bool = False
    last_used: Optional[datetime] = None
    size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category.value,
            'path': self.path,
            'rack_chain': self.rack_chain,
            'parameters': self.parameters,
            'is_favorite': self.is_favorite,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'size_bytes': self.size_bytes
        }


class PresetCatalog:
    """Серверный каталог пресетов"""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self._lock = threading.Lock()
        self._presets: Dict[str, PresetInfo] = {}
        self._categories: Dict[PresetCategory, List[str]] = {
            cat: [] for cat in PresetCategory
        }
        self._recent_presets: List[str] = []
        self._favorites: List[str] = []
        self._preset_cache_file = Path("data/preset_cache.json")
        self._load_cache()

    def initialize(self) -> bool:
        """
        Инициализация каталога пресетов.

        Returns:
            bool: True если успешно
        """
        try:
            # Получаем путь к пресетам из конфигурации
            preset_folder = self.config.get('gr7', 'preset_folder', '')
            if not preset_folder:
                if self.logger:
                    self.logger.log_preset("Папка пресетов не указана в конфигурации", "warning")
                # Попробуем найти стандартные папки Guitar Rig
                preset_folder = self._find_default_preset_folders()

            if not preset_folder:
                if self.logger:
                    self.logger.log_preset("Не найдены папки с пресетами", "error")
                return False

            if self.logger:
                self.logger.log_preset(f"Поиск пресетов в: {preset_folder}", "info")

            # Сканируем папки с пресетами
            self._scan_preset_folders(preset_folder)

            # Загружаем кэш
            self._load_cache()

            if self.logger:
                self.logger.log_preset(f"Загружено пресетов: {len(self._presets)}", "info")

            return True

        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка инициализации каталога: {e}", "error")
                self.logger.log_preset(traceback.format_exc(), "error")
            return False

    def _find_default_preset_folders(self) -> Optional[str]:
        """Поиск стандартных папок пресетов Guitar Rig"""
        possible_paths = [
            Path("C:/Program Files/Native Instruments/Guitar Rig 7/Presets"),
            Path("C:/Users/Саша/Documents/Native Instruments/Guitar Rig 7/Presets"),
            Path("C:/Users/Саша/AppData/Roaming/Native Instruments/Guitar Rig 7/Presets"),
        ]

        for path in possible_paths:
            if path.exists():
                if self.logger:
                    self.logger.log_preset(f"Найдена папка пресетов: {path}", "info")
                return str(path)

        return None

    def _scan_preset_folders(self, root_folder: str) -> None:
        """Сканирование папок с пресетами"""
        try:
            root_path = Path(root_folder)

            if not root_path.exists():
                if self.logger:
                    self.logger.log_preset(f"Папка не существует: {root_path}", "error")
                return

            # Ищем файлы .nkp (Guitar Rig preset files)
            preset_files = list(root_path.rglob("*.nkp"))

            if self.logger:
                self.logger.log_preset(f"Найдено пресетов: {len(preset_files)}", "info")

            for preset_file in preset_files:
                self._add_preset_from_file(preset_file)

        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка сканирования папок: {e}", "error")
                self.logger.log_preset(traceback.format_exc(), "error")

    def _add_preset_from_file(self, file_path: Path) -> None:
        """Добавление пресета из файла"""
        try:
            # Определяем категорию
            rel_path = file_path.relative_to(file_path.parent.parent)
            category = self._determine_category(file_path)

            # Создаем ID пресета
            preset_id = f"{category.value}_{file_path.stem}"

            # Проверяем, есть ли уже такой пресет
            if preset_id in self._presets:
                return

            # Получаем размер файла
            size_bytes = file_path.stat().st_size

            # Создаем информацию о пресете
            preset_info = PresetInfo(
                id=preset_id,
                name=file_path.stem,
                category=category,
                path=str(file_path),
                size_bytes=size_bytes
            )

            # Добавляем в каталог
            with self._lock:
                self._presets[preset_id] = preset_info
                self._categories[category].append(preset_id)

            if self.logger:
                self.logger.log_preset(f"Добавлен пресет: {preset_id}", "debug")

        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка добавления пресета {file_path}: {e}", "error")

    def _determine_category(self, file_path: Path) -> PresetCategory:
        """Определение категории пресета"""
        # Проверяем папки favorites
        if 'Favorites' in file_path.parts:
            return PresetCategory.FAVORITES

        # Проверяем папки recent
        if 'Recent' in file_path.parts:
            return PresetCategory.RECENT

        # Проверяем папки user
        if 'User' in file_path.parts or 'User Presets' in file_path.parts:
            return PresetCategory.USER

        # По умолчанию - factory
        return PresetCategory.FACTORY

    def get_preset(self, preset_id: str) -> Optional[PresetInfo]:
        """Получение информации о пресете"""
        try:
            with self._lock:
                return self._presets.get(preset_id)
        except Exception:
            return None

    def get_all_presets(self, category: Optional[PresetCategory] = None) -> List[PresetInfo]:
        """Получение списка всех пресетов"""
        try:
            with self._lock:
                if category:
                    preset_ids = self._categories.get(category, [])
                    return [self._presets[pid] for pid in preset_ids if pid in self._presets]
                else:
                    return list(self._presets.values())
        except Exception:
            return []

    def get_preset_list(self, category: Optional[PresetCategory] = None,
                        search_query: Optional[str] = None,
                        limit: Optional[int] = None,
                        offset: int = 0) -> Dict[str, Any]:
        """
        Получение списка пресетов (API для мобильного клиента).

        Args:
            category: Категория пресетов
            search_query: Поисковый запрос
            limit: Лимит результатов
            offset: Смещение

        Returns:
            Dict: Список пресетов с метаданными
        """
        try:
            with self._lock:
                presets = self._get_filtered_presets(category, search_query)

                # Пагинация
                if limit:
                    presets = presets[offset:offset + limit]

                # Формируем компактный ответ
                result = {
                    'total': len(self._get_filtered_presets(category, search_query)),
                    'presets': [p.to_dict() for p in presets],
                    'categories': {cat.value: len(ids) for cat, ids in self._categories.items()}
                }

                return result
        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка получения списка пресетов: {e}", "error")
            return {'total': 0, 'presets': [], 'categories': {}}

    def _get_filtered_presets(self, category: Optional[PresetCategory],
                              search_query: Optional[str]) -> List[PresetInfo]:
        """Фильтрация пресетов"""
        try:
            presets = []

            if category:
                preset_ids = self._categories.get(category, [])
                presets = [self._presets[pid] for pid in preset_ids if pid in self._presets]
            else:
                presets = list(self._presets.values())

            if search_query:
                query = search_query.lower()
                presets = [p for p in presets if query in p.name.lower()]

            return presets
        except Exception:
            return []

    def select_preset(self, preset_id: str) -> bool:
        """
        Выбор пресета.

        Args:
            preset_id: ID пресета

        Returns:
            bool: True если успешно
        """
        try:
            with self._lock:
                if preset_id not in self._presets:
                    if self.logger:
                        self.logger.log_preset(f"Пресет не найден: {preset_id}", "error")
                    return False

                # Обновляем last_used
                preset = self._presets[preset_id]
                preset.last_used = datetime.now()

                # Добавляем в recent
                if preset_id not in self._recent_presets:
                    self._recent_presets.insert(0, preset_id)
                    self._recent_presets = self._recent_presets[:100]  # Храним последние 100

                if self.logger:
                    self.logger.log_preset(f"Выбран пресет: {preset_id}", "info")

                return True
        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка выбора пресета: {e}", "error")
            return False

    def next_preset(self) -> Optional[str]:
        """Следующий пресет"""
        try:
            with self._lock:
                current = self._categories.get(PresetCategory.FACTORY, [])
                if not current:
                    return None

                # Если есть текущий пресет, ищем следующий
                if self._presets.get('current_preset'):
                    current_preset = self._presets['current_preset']
                    try:
                        idx = current.index(current_preset.id)
                        if idx + 1 < len(current):
                            return current[idx + 1]
                    except (KeyError, ValueError):
                        pass

                # Иначе возвращаем первый
                return current[0]
        except Exception:
            return None

    def prev_preset(self) -> Optional[str]:
        """Предыдущий пресет"""
        try:
            with self._lock:
                current = self._categories.get(PresetCategory.FACTORY, [])
                if not current:
                    return None

                # Если есть текущий пресет, ищем предыдущий
                if self._presets.get('current_preset'):
                    current_preset = self._presets['current_preset']
                    try:
                        idx = current.index(current_preset.id)
                        if idx > 0:
                            return current[idx - 1]
                    except (KeyError, ValueError):
                        pass

                # Иначе возвращаем последний
                return current[-1]
        except Exception:
            return None

    def toggle_favorite(self, preset_id: str) -> bool:
        """
        Переключение избранного.

        Args:
            preset_id: ID пресета

        Returns:
            bool: True если успешно
        """
        try:
            with self._lock:
                if preset_id not in self._presets:
                    return False

                preset = self._presets[preset_id]
                preset.is_favorite = not preset.is_favorite

                if preset.is_favorite:
                    if preset_id not in self._favorites:
                        self._favorites.append(preset_id)
                else:
                    if preset_id in self._favorites:
                        self._favorites.remove(preset_id)

                if self.logger:
                    self.logger.log_preset(f"{'Добавлен' if preset.is_favorite else 'Удален'} в избранное: {preset_id}", "info")

                return True
        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка переключения избранного: {e}", "error")
            return False

    def get_current_preset(self) -> Optional[PresetInfo]:
        """Получение текущего выбранного пресета"""
        try:
            with self._lock:
                return self._presets.get('current_preset')
        except Exception:
            return None

    def set_current_preset(self, preset_id: str) -> bool:
        """
        Установка текущего пресета.

        Args:
            preset_id: ID пресета

        Returns:
            bool: True если успешно
        """
        try:
            with self._lock:
                if preset_id not in self._presets:
                    return False

                self._presets['current_preset'] = self._presets[preset_id]
                return True
        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка установки текущего пресета: {e}", "error")
            return False

    def get_recent_presets(self, limit: int = 20) -> List[PresetInfo]:
        """Получение списка недавних пресетов"""
        try:
            with self._lock:
                recent_ids = self._recent_presets[:limit]
                return [self._presets[pid] for pid in recent_ids if pid in self._presets]
        except Exception:
            return []

    def get_favorites(self) -> List[PresetInfo]:
        """Получение списка избранных пресетов"""
        try:
            with self._lock:
                favorite_ids = self._favorites
                return [self._presets[pid] for pid in favorite_ids if pid in self._presets]
        except Exception:
            return []

    def search_presets(self, query: str, limit: int = 50) -> List[PresetInfo]:
        """
        Поиск пресетов.

        Args:
            query: Поисковый запрос
            limit: Лимит результатов

        Returns:
            List: Список найденных пресетов
        """
        try:
            with self._lock:
                results = self._get_filtered_presets(None, query)
                return results[:limit]
        except Exception:
            return []

    def get_rack_chain(self, preset_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Получение rack chain для пресета.

        Args:
            preset_id: ID пресета

        Returns:
            List: Rack chain или None
        """
        try:
            with self._lock:
                preset = self._presets.get(preset_id)
                if preset:
                    return preset.rack_chain
                return None
        except Exception:
            return None

    def get_parameters(self, preset_id: str) -> Optional[Dict[str, float]]:
        """
        Получение параметров пресета.

        Args:
            preset_id: ID пресета

        Returns:
            Dict: Параметры или None
        """
        try:
            with self._lock:
                preset = self._presets.get(preset_id)
                if preset:
                    return preset.parameters
                return None
        except Exception:
            return None

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики каталога"""
        try:
            with self._lock:
                return {
                    'total_presets': len(self._presets),
                    'categories': {cat.value: len(ids) for cat, ids in self._categories.items()},
                    'favorites_count': len(self._favorites),
                    'recent_count': len(self._recent_presets),
                    'current_preset': self._presets.get('current_preset', {}).name if self._presets.get('current_preset') else None
                }
        except Exception:
            return {'total_presets': 0, 'categories': {}, 'favorites_count': 0, 'recent_count': 0, 'current_preset': None}

    def _load_cache(self) -> None:
        """Загрузка кэша пресетов"""
        try:
            if self._preset_cache_file.exists():
                with open(self._preset_cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)

                # Восстанавливаем избранные и недавние
                self._favorites = cache.get('favorites', [])
                self._recent_presets = cache.get('recent', [])

                if self.logger:
                    self.logger.log_preset(f"Загружен кэш: {len(self._favorites)} избранных, {len(self._recent_presets)} недавних", "info")

        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка загрузки кэша: {e}", "warning")

    def _save_cache(self) -> None:
        """Сохранение кэша пресетов"""
        try:
            # Создаем директорию если нужно
            self._preset_cache_file.parent.mkdir(parents=True, exist_ok=True)

            cache = {
                'favorites': self._favorites,
                'recent': self._recent_presets,
                'last_updated': datetime.now().isoformat()
            }

            with open(self._preset_cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

        except Exception as e:
            if self.logger:
                self.logger.log_preset(f"Ошибка сохранения кэша: {e}", "warning")

    def shutdown(self) -> None:
        """Остановка и сохранение кэша"""
        self._save_cache()
        if self.logger:
            self.logger.log_preset("PresetCatalog остановлен", "info")