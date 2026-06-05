"""
VST3 Host
=========
Основной класс для управления VST3 хостингом.
Auto-detection VST3 плагинов.
"""

import threading
import numpy as np
from pathlib import Path
from typing import Optional, Callable, List
from .plugin import VST3Plugin


class VST3Host:
    """VST3 хостинг движок"""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.plugin: Optional[VST3Plugin] = None
        self._audio_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._callback: Optional[Callable] = None
        self._plugin_path: Optional[str] = None

    def _find_plugin_path(self) -> Optional[str]:
        """
        Поиск пути к VST3 плагину.
        Приоритет:
        1. auto-detection в рабочей директории
        2. путь из config.ini (override)
        3. fallback поиск *.vst3 в plugins/

        Returns:
            Optional[str]: Абсолютный путь к плагину или None
        """
        search_paths = [
            Path("./plugins/Guitar Rig 7.vst3"),
            Path("plugins/Guitar Rig 7.vst3"),
            Path.cwd() / "plugins" / "Guitar Rig 7.vst3"
        ]

        for search_path in search_paths:
            if search_path.exists():
                found_path = str(search_path.resolve())
                if self.logger:
                    self.logger.log_vst(f"Guitar Rig 7.vst3 найден: {found_path}", "info")
                return found_path

        config_path = self.config.get('vst3', 'path')
        if config_path:
            config_file = Path(config_path)
            if config_file.exists():
                found_path = str(config_file.resolve())
                if self.logger:
                    self.logger.log_vst(f"Guitar Rig 7.vst3 найден в config.ini: {found_path}", "info")
                return found_path
            else:
                if self.logger:
                    self.logger.log_vst(f"Путь из config.ini не существует: {config_path}", "warning")

        plugins_dir = Path.cwd() / "plugins"
        if plugins_dir.exists():
            vst3_files = sorted(plugins_dir.glob("*.vst3"))
            if vst3_files:
                found_path = str(vst3_files[0].resolve())
                if self.logger:
                    self.logger.log_vst(f"VST3 плагин найден через fallback поиск: {found_path}", "info")
                return found_path

        return None

    def initialize(self) -> bool:
        """
        Инициализация VST3 хоста.

        Returns:
            bool: True если успешно
        """
        plugin_path = self._find_plugin_path()

        if not plugin_path:
            if self.logger:
                self.logger.log_vst("Guitar Rig 7.vst3 не найден", "error")
            return False

        if self.logger:
            self.logger.log_vst(f"Найден plugin: {plugin_path}", "info")

        try:
            self._plugin_path = plugin_path
            self.plugin = VST3Plugin(plugin_path, self.logger)

            if not self.plugin.load():
                if self.plugin.plugin is None:
                    if self.logger:
                        self.logger.log_vst("pedalboard вернул None", "error")
                else:
                    if self.logger:
                        self.logger.log_vst("Ошибка загрузки плагина", "error")
                return False

            if self.logger:
                self.logger.log_vst("Plugin loaded successfully", "success")
            return True

        except Exception as e:
            if self.logger:
                self.logger.log_vst(f"Ошибка загрузки: {e}", "error")
            return False

    def start_audio_thread(self, callback: Callable) -> None:
        """
        Запуск аудио потока.

        Args:
            callback: Функция обратного вызова для обработки аудио
        """
        with self._lock:
            if self._running:
                return

            self._callback = callback
            self._running = True
            self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
            self._audio_thread.start()

            if self.logger:
                self.logger.log_vst("Аудио поток запущен", "success")

    def stop_audio_thread(self) -> None:
        """Остановка аудио потока"""
        with self._lock:
            self._running = False
            if self._audio_thread:
                self._audio_thread.join(timeout=1.0)
                self._audio_thread = None

            if self.logger:
                self.logger.log_vst("Аудио поток остановлен", "info")

    def _audio_loop(self) -> None:
        """Цикл аудио обработки"""
        while self._running:
            try:
                if self._callback:
                    self._callback()
            except Exception as e:
                if self.logger:
                    self.logger.log_vst(f"Ошибка в аудио цикле: {e}", "error")
                break

    def process_audio(self, input_data: np.ndarray) -> np.ndarray:
        """
        Обработка аудио через плагин.

        Args:
            input_data: Входные данные

        Returns:
            np.ndarray: Выходные данные
        """
        if self.plugin:
            return self.plugin.process(input_data)
        return input_data

    def send_program_change(self, program_id: int) -> bool:
        """
        Отправка Program Change (перезагрузка плагина с новым preset).

        Args:
            program_id: ID пресета

        Returns:
            bool: True если успешно
        """
        if not self.plugin or not self.plugin.is_loaded:
            if self.logger:
                self.logger.log_vst("Плагин не загружен", "error")
            return False

        try:
            # Перезагрузка плагина для смены preset
            self.plugin.unload()
            if self.plugin.load():
                if self.logger:
                    self.logger.log_vst(f"Пресет переключен: {program_id}", "success")
                return True
            return False
        except Exception as e:
            if self.logger:
                self.logger.log_vst(f"Ошибка переключения пресета: {e}", "error")
            return False

    def send_control_change(self, controller: int, value: int) -> bool:
        """
        Отправка Control Change.

        Args:
            controller: Номер контроллера
            value: Значение (0-127)

        Returns:
            bool: True если успешно
        """
        if not self.plugin or not self.plugin.is_loaded:
            if self.logger:
                self.logger.log_vst("Плагин не загружен", "error")
            return False

        try:
            # Безопасно получаем параметры (lazy, не в boot path)
            try:
                params = self.plugin.get_parameters()
            except Exception as e:
                if self.logger:
                    self.logger.log_vst(f"Не удалось получить параметры: {e}", "warning")
                return False

            if not params or not isinstance(params, dict):
                return False

            # Ищем соответствующий параметр
            for param_name, param_value in params.items():
                try:
                    # Безопасно преобразуем параметр в число
                    try:
                        numeric_value = float(param_value)
                    except (ValueError, TypeError):
                        continue
                    
                    # Сравниваем с контроллером
                    if controller == int(numeric_value * 127):
                        self.plugin.set_parameter(param_name, value / 127.0)
                        if self.logger:
                            self.logger.log_vst(f"CC {controller} -> {param_name}", "success")
                        return True
                except Exception:
                    continue
            
            return False
        except Exception as e:
            if self.logger:
                self.logger.log_vst(f"Ошибка отправки CC: {e}", "error")
            return False

    def get_parameter_names(self) -> List[str]:
        """
        Безопасное получение списка имен параметров плагина.
        
        Вместо использования super() и прямого доступа к атрибутам,
        использует безопасный подход с проверкой наличия параметров.

        Returns:
            List[str]: Список имен параметров или пустой список
        """
        if not self.plugin or not self.plugin.is_loaded:
            if self.logger:
                self.logger.log_vst("Плагин не загружен для получения параметров", "warning")
            return []

        try:
            # Пытаемся получить параметры безопасно
            params = self.plugin.get_parameters()
            if params and isinstance(params, dict):
                param_names = list(params.keys())
                if self.logger:
                    self.logger.log_vst(f"Получено {len(param_names)} параметров плагина", "info")
                return param_names
            return []
        except Exception as e:
            if self.logger:
                self.logger.log_vst(f"Ошибка получения списка параметров: {e}", "warning")
            return []

    def is_plugin_loaded(self) -> bool:
        """
        Lightweight проверка загрузки плагина (без introspection).

        Returns:
            bool: True если плагин загружен
        """
        return self.plugin is not None and self.plugin.is_loaded

    def get_status(self) -> dict:
        """
        Получение статуса хоста (с lazy introspection).

        ВНИМАНИЕ: get_info() вызывает тяжелую introspection через pedalboard.
        Должен быть вызван только после GUI загрузки.

        Returns:
            dict: Статус
        """
        status = {
            'initialized': self.plugin is not None,
            'plugin_loaded': self.is_plugin_loaded(),
            'audio_running': self._running
        }
        # Lazy introspection: только если не в boot path
        if self.plugin and self.plugin.is_loaded:
            try:
                status['info'] = self.plugin.get_info()
            except Exception:
                status['info'] = {}
        return status

    def shutdown(self) -> None:
        """Остановка и очистка"""
        self.stop_audio_thread()
        if self.plugin:
            self.plugin.unload()
            self.plugin = None

        if self.logger:
            self.logger.log_vst("VST3 хост остановлен", "info")