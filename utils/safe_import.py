"""
SafeImport
==========
Безопасный импорт тяжелых библиотек с timeout и graceful degradation.
"""

import threading
import time
from typing import Optional, Tuple, Any
from core.logger import Logger


class SafeImport:
    """Безопасный импорт с timeout и обработкой ошибок"""

    @staticmethod
    def import_module(module_name: str, timeout: float = 5.0) -> Tuple[bool, Optional[Any], Optional[str]]:
        """
        Безопасный импорт модуля с timeout.

        Args:
            module_name: Имя модуля
            timeout: Timeout в секундах

        Returns:
            Tuple[success, module, error_message]
        """
        result = [None, None, None]  # [success, module, error]

        def _import():
            try:
                module = __import__(module_name)
                result[0] = True
                result[1] = module
            except Exception as e:
                result[0] = False
                result[2] = str(e)

        # Запускаем в отдельном thread
        thread = threading.Thread(target=_import, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        # Проверяем timeout
        if thread.is_alive():
            return False, None, f"Import timeout after {timeout}s"

        return result[0], result[1], result[2]

    @staticmethod
    def import_symbols(module_name: str, symbols: list, timeout: float = 5.0) -> Tuple[bool, dict, Optional[str]]:
        """
        Безопасный импорт модуля и символов с timeout.

        Args:
            module_name: Имя модуля
            symbols: Список символов для импорта
            timeout: Timeout в секундах

        Returns:
            Tuple[success, symbols_dict, error_message]
        """
        success, module, error = SafeImport.import_module(module_name, timeout)
        
        if not success:
            return False, {}, error

        try:
            symbols_dict = {}
            for symbol in symbols:
                try:
                    symbols_dict[symbol] = getattr(module, symbol)
                except AttributeError:
                    return False, {}, f"Symbol '{symbol}' not found in {module_name}"

            return True, symbols_dict, None
        except Exception as e:
            return False, {}, f"Error importing symbols: {e}"