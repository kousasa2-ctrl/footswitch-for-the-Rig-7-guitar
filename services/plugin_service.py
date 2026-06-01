"""
PluginService
==============
Сервис управления VST3 плагином Guitar Rig 7.
"""

import threading
import traceback
from typing import Optional, Dict, Any, List
from vst3.host import VST3Host
from core.state_manager import StateManager
from core.logger import Logger
from services.preset_catalog import PresetCatalog


class PluginService:
    """Сервис управления VST3 плагином"""

    def __init__(self, config, state_manager: StateManager, logger: Logger,
                 preset_catalog: Optional[PresetCatalog] = None):
        self.config = config
        self.state_manager = state_manager
        self.logger = logger
        self.host: Optional[VST3Host] = None
        self._initialized = False
        self._preset_catalog = preset_catalog
        self._current_preset_id: Optional[str] = None
        self._lock = threading.Lock()

    def initialize(self) -> bool:
        """
        Инициализация сервиса.

        Returns:
            bool: True если успешно
        """
        try:
            self.host = VST3Host(self.config, self.logger)

            if not self.host.initialize():
                self.state_manager.update_state(plugin_loaded=False)
                if self.logger:
                    self.logger.log_plugin("VST3 хост не инициализирован", "error")
                return False

            # Проверяем, что плагин реально загружен
            status = self.host.get_status()
            if not status.get('plugin_loaded'):
                self.state_manager.update_state(plugin_loaded=False)
                if self.logger:
                    self.logger.log_plugin("VST3 плагин не загружен", "error")
                return False

            self._initialized = True
            self.state_manager.update_state(plugin_loaded=True)
            if self.logger:
                self.logger.log_plugin("VST3 плагин загружен", "info")

            return True

        except Exception as e:
            self.state_manager.update_state(plugin_loaded=False)
            if self.logger:
                self.logger.log_plugin(f"Ошибка инициализации: {e}", "error")
                self.logger.log_plugin(traceback.format_exc(), "error")
            return False

    def switch_preset(self, preset_id: int) -> bool:
        """
        Переключение пресета через Program Change.

        Args:
            preset_id: ID пресета (0-127)

        Returns:
            bool: True если успешно
        """
        try:
            if not self._initialized or not self.host:
                if self.logger:
                    self.logger.log_plugin("Плагин не загружен", "error")
                return False

            success = self.host.send_program_change(preset_id)
            if success:
                self.state_manager.update_state(current_preset=preset_id)
                if self.logger:
                    self.logger.log_plugin(f"Пресет переключен: {preset_id}", "info")
            return success
        except Exception as e:
            if self.logger:
                self.logger.log_plugin(f"Ошибка переключения: {e}", "error")
                self.logger.log_plugin(traceback.format_exc(), "error")
            return False

    def switch_preset_by_id(self, preset_id: str) -> bool:
        """
        Переключение пресета по ID из каталога.

        Args:
            preset_id: ID пресета из каталога

        Returns:
            bool: True если успешно
        """
        try:
            if not self._preset_catalog:
                if self.logger:
                    self.logger.log_plugin("PresetCatalog не инициализирован", "error")
                return False

            with self._lock:
                preset = self._preset_catalog.get_preset(preset_id)
                if not preset:
                    if self.logger:
                        self.logger.log_plugin(f"Пресет не найден: {preset_id}", "error")
                    return False

                # Получаем индекс пресета
                presets = self._preset_catalog.get_all_presets()
                try:
                    index = next(i for i, p in enumerate(presets) if p.id == preset_id)
                    return self.switch_preset(index)
                except (StopIteration, ValueError):
                    if self.logger:
                        self.logger.log_plugin(f"Не удалось найти индекс для пресета: {preset_id}", "error")
                    return False
        except Exception as e:
            if self.logger:
                self.logger.log_plugin(f"Ошибка переключения по ID: {e}", "error")
                self.logger.log_plugin(traceback.format_exc(), "error")
            return False

    def get_preset_info(self, preset_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение информации о пресете.

        Args:
            preset_id: ID пресета

        Returns:
            Dict: Информация о пресете
        """
        try:
            if not self._preset_catalog:
                return None

            with self._lock:
                presets = self._preset_catalog.get_all_presets()
                try:
                    preset = presets[preset_id]
                    return {
                        'id': preset.id,
                        'name': preset.name,
                        'category': preset.category.value,
                        'rack_chain': preset.rack_chain,
                        'parameters': preset.parameters
                    }
                except (IndexError, KeyError):
                    return None
        except Exception:
            return None

    def get_all_presets_info(self) -> List[Dict[str, Any]]:
        """
        Получение информации о всех доступных пресетах.

        Returns:
            List: Список информации о пресетах
        """
        try:
            if not self._preset_catalog:
                return []

            with self._lock:
                presets = self._preset_catalog.get_all_presets()
                return [p.to_dict() for p in presets]
        except Exception:
            return []

    def get_current_preset_info(self) -> Optional[Dict[str, Any]]:
        """Получение информации о текущем пресете"""
        try:
            if not self._preset_catalog:
                return None

            with self._lock:
                preset = self._preset_catalog.get_current_preset()
                if preset:
                    return preset.to_dict()
                return None
        except Exception:
            return None

    def get_rack_chain(self) -> Optional[List[Dict[str, Any]]]:
        """
        Получение rack chain текущего пресета.

        Returns:
            List: Rack chain или None
        """
        try:
            if not self._preset_catalog:
                return None

            with self._lock:
                preset = self._preset_catalog.get_current_preset()
                if preset:
                    return preset.rack_chain
                return None
        except Exception:
            return None

    def get_parameters(self) -> Optional[Dict[str, float]]:
        """
        Получение параметров текущего пресета.

        Returns:
            Dict: Параметры или None
        """
        try:
            if not self._preset_catalog:
                return None

            with self._lock:
                preset = self._preset_catalog.get_current_preset()
                if preset:
                    return preset.parameters
                return None
        except Exception:
            return None

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса"""
        try:
            if self.host:
                status = self.host.get_status()
                status['initialized'] = self._initialized
                status['current_preset_id'] = self._current_preset_id
                return status
            return {'initialized': False, 'plugin_loaded': False}
        except Exception:
            return {'initialized': False, 'plugin_loaded': False}

    def shutdown(self) -> None:
        """Остановка сервиса"""
        try:
            if self.host:
                self.host.shutdown()
                self.host = None
            self._initialized = False
            self._current_preset_id = None
            if self.logger:
                self.logger.log_plugin("PluginService остановлен", "info")
        except Exception:
            pass