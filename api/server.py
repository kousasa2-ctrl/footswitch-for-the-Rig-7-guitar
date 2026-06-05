"""
API Server
==========
REST API для мобильного клиента.
"""

import json
import threading
import traceback
from typing import Optional, Dict, Any, Callable
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import queue
from dataclasses import dataclass, field
from enum import Enum

from core.logger import Logger
from services.preset_catalog import PresetCatalog
from services.player_service import PlayerService
from services.plugin_service import PluginService


class APIResponse:
    """Класс для формирования ответов API"""

    @staticmethod
    def success(data: Any = None, message: str = "OK") -> Dict[str, Any]:
        """Успешный ответ"""
        return {
            'success': True,
            'data': data,
            'message': message
        }

    @staticmethod
    def error(message: str, code: int = 400) -> Dict[str, Any]:
        """Ошибка"""
        return {
            'success': False,
            'error': message,
            'code': code
        }


@dataclass
class APIMessage:
    """Сообщение для обработки"""
    method: str
    path: str
    query: Dict[str, list]
    body: Optional[Dict[str, Any]]
    response_queue: queue.Queue


class APIHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP запросов"""

    def __init__(self, request, client_address, server, api_server):
        self.api_server = api_server
        super().__init__(request, client_address, server)

    def log_message(self, format, *args):
        """Отключение стандартного логирования"""
        pass

    def do_GET(self):
        """Обработка GET запросов"""
        self._handle_request('GET')

    def do_POST(self):
        """Обработка POST запросов"""
        self._handle_request('POST')

    def _handle_request(self, method: str):
        """Обработка запроса"""
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            # Чтение тела запроса
            body = None
            if method == 'POST':
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    body = json.loads(self.rfile.read(content_length))

            # Создаем сообщение
            message = APIMessage(
                method=method,
                path=path,
                query=query,
                body=body,
                response_queue=queue.Queue()
            )

            # Отправляем в обработчик
            self.api_server._process_message(message)

            # Получаем ответ
            try:
                response = message.response_queue.get(timeout=5.0)
            except queue.Empty:
                response = APIResponse.error("Timeout")

            # Отправляем ответ
            self._send_response(response)
        except Exception as e:
            if self.api_server and self.api_server.logger:
                self.api_server.logger.log_api(f"Ошибка обработки запроса: {e}", "error")
            self._send_response(APIResponse.error(str(e)))

    def _send_response(self, response: Dict[str, Any]):
        """Отправка HTTP ответа"""
        try:
            self.send_response(response.get('code', 200))
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
        except Exception:
            pass

    def end_headers(self):
        """Добавление CORS заголовков"""
        try:
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        except Exception:
            pass
        super().end_headers()


class APIServer:
    """Сервер API"""

    def __init__(self, config, logger: Logger,
                 preset_catalog: PresetCatalog,
                 player_service: PlayerService,
                 plugin_service: PluginService):
        self.config = config
        self.logger = logger
        self.preset_catalog = preset_catalog
        self.player_service = player_service
        self.plugin_service = plugin_service
        self._server: Optional[HTTPServer] = None
        self._running = False
        self._lock = threading.Lock()
        self._message_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._host = '0.0.0.0'  # Явный bind host без DNS lookup

    def initialize(self) -> bool:
        """Инициализация сервера"""
        try:
            port = int(self.config.get('wifi', 'port', '5000'))
            handler = partial(APIHandler, api_server=self)
            self._server = HTTPServer(('0.0.0.0', port), handler)

            if self.logger:
                self.logger.log_api(f"API сервер инициализирован на порту {port}", "info")

            return True

        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка запуска API сервера: {e}", "error")
                self.logger.log_api(traceback.format_exc(), "error")
            return False

    def _process_message(self, message: APIMessage):
        """Обработка сообщения"""
        try:
            response = self._route_request(message)
            message.response_queue.put(response)
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка обработки запроса: {e}", "error")
                self.logger.log_api(traceback.format_exc(), "error")
            message.response_queue.put(APIResponse.error(str(e)))

    def _route_request(self, message: APIMessage) -> Dict[str, Any]:
        """Маршрутизация запроса"""
        try:
            # Префиксы API
            if message.path.startswith('/api/presets'):
                return self._handle_preset_request(message)
            elif message.path.startswith('/api/player'):
                return self._handle_player_request(message)
            elif message.path.startswith('/api/plugin'):
                return self._handle_plugin_request(message)
            elif message.path.startswith('/api/status'):
                return self._handle_status_request(message)
            elif message.path.startswith('/api/transport'):
                return self._handle_transport_request(message)
            else:
                return APIResponse.error("Not Found", 404)
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка маршрутизации: {e}", "error")
            return APIResponse.error(str(e))

    def _handle_preset_request(self, message: APIMessage) -> Dict[str, Any]:
        """Обработка запросов пресетов"""
        try:
            path = message.path

            # GET /api/presets - список всех пресетов
            if path == '/api/presets':
                category = message.query.get('category', [None])[0]
                search = message.query.get('search', [None])[0]
                limit = message.query.get('limit', [None])
                offset = message.query.get('offset', [None])

                limit = int(limit[0]) if limit and limit[0] else None
                offset = int(offset[0]) if offset and offset[0] else 0

                if category:
                    cat_enum = self.preset_catalog._categories.keys()
                    try:
                        category = next(c for c in cat_enum if c.value == category)
                    except StopIteration:
                        return APIResponse.error("Invalid category")

                data = self.preset_catalog.get_preset_list(
                    category=category,
                    search_query=search,
                    limit=limit,
                    offset=offset
                )
                return APIResponse.success(data)

            # GET /api/presets/current - текущий пресет
            elif path == '/api/presets/current':
                preset = self.preset_catalog.get_current_preset()
                if preset:
                    return APIResponse.success(preset.to_dict())
                return APIResponse.error("No preset selected")

            # POST /api/presets/select - выбор пресета
            elif path == '/api/presets/select':
                if not message.body or 'id' not in message.body:
                    return APIResponse.error("Missing preset ID")

                preset_id = message.body['id']
                if self.preset_catalog.select_preset(preset_id):
                    return APIResponse.success(message="Preset selected")
                return APIResponse.error("Failed to select preset")

            # POST /api/presets/next - следующий пресет
            elif path == '/api/presets/next':
                preset_id = self.preset_catalog.next_preset()
                if preset_id:
                    return APIResponse.success({'id': preset_id})
                return APIResponse.error("No more presets")

            # POST /api/presets/prev - предыдущий пресет
            elif path == '/api/presets/prev':
                preset_id = self.preset_catalog.prev_preset()
                if preset_id:
                    return APIResponse.success({'id': preset_id})
                return APIResponse.error("No previous presets")

            # POST /api/presets/favorite - избранное
            elif path == '/api/presets/favorite':
                if not message.body or 'id' not in message.body:
                    return APIResponse.error("Missing preset ID")

                preset_id = message.body['id']
                if self.preset_catalog.toggle_favorite(preset_id):
                    return APIResponse.success(message="Favorite toggled")
                return APIResponse.error("Failed to toggle favorite")

            # GET /api/presets/favorites - избранные пресеты
            elif path == '/api/presets/favorites':
                presets = self.preset_catalog.get_favorites()
                return APIResponse.success([p.to_dict() for p in presets])

            # GET /api/presets/recent - недавние пресеты
            elif path == '/api/presets/recent':
                presets = self.preset_catalog.get_recent_presets()
                return APIResponse.success([p.to_dict() for p in presets])

            # GET /api/presets/rack - rack chain
            elif path == '/api/presets/rack':
                if not message.body or 'id' not in message.body:
                    return APIResponse.error("Missing preset ID")

                rack_chain = self.preset_catalog.get_rack_chain(message.body['id'])
                if rack_chain:
                    return APIResponse.success(rack_chain)
                return APIResponse.error("Rack chain not available")

            # GET /api/presets/parameters - параметры
            elif path == '/api/presets/parameters':
                if not message.body or 'id' not in message.body:
                    return APIResponse.error("Missing preset ID")

                params = self.preset_catalog.get_parameters(message.body['id'])
                if params:
                    return APIResponse.success(params)
                return APIResponse.error("Parameters not available")

            return APIResponse.error("Not Found", 404)
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка обработки пресетов: {e}", "error")
            return APIResponse.error(str(e))

    def _handle_player_request(self, message: APIMessage) -> Dict[str, Any]:
        """Обработка запросов плеера"""
        try:
            path = message.path

            # GET /api/player/status - статус плеера
            if path == '/api/player/status':
                data = self.player_service.get_state()
                return APIResponse.success(data)

            # POST /api/player/play - воспроизведение
            elif path == '/api/player/play':
                if not message.body or 'track_id' not in message.body:
                    return APIResponse.error("Missing track ID")

                track_id = message.body['track_id']
                if self.player_service.play_track(track_id):
                    return APIResponse.success(message="Playing")
                return APIResponse.error("Failed to play")

            # POST /api/player/stop - остановка
            elif path == '/api/player/stop':
                self.player_service.stop()
                return APIResponse.success(message="Stopped")

            # POST /api/player/pause - пауза
            elif path == '/api/player/pause':
                self.player_service.pause()
                return APIResponse.success(message="Paused")

            # POST /api/player/resume - продолжение
            elif path == '/api/player/resume':
                self.player_service.resume()
                return APIResponse.success(message="Resumed")

            # POST /api/player/next - следующий трек
            elif path == '/api/player/next':
                track_id = self.player_service.next_track()
                if track_id:
                    return APIResponse.success({'id': track_id})
                return APIResponse.error("No more tracks")

            # POST /api/player/prev - предыдущий трек
            elif path == '/api/player/prev':
                track_id = self.player_service.prev_track()
                if track_id:
                    return APIResponse.success({'id': track_id})
                return APIResponse.error("No previous tracks")

            # POST /api/player/volume - громкость
            elif path == '/api/player/volume':
                if not message.body or 'volume' not in message.body:
                    return APIResponse.error("Missing volume")

                volume = float(message.body['volume'])
                self.player_service.set_volume(volume)
                return APIResponse.success(message="Volume set")

            # POST /api/player/seek - перемотка
            elif path == '/api/player/seek':
                if not message.body or 'position' not in message.body:
                    return APIResponse.error("Missing position")

                position = float(message.body['position'])
                self.player_service.seek(position)
                return APIResponse.success(message="Seeked")

            # GET /api/player/tracks - список треков
            elif path == '/api/player/tracks':
                search = message.query.get('search', [None])[0]
                limit = message.query.get('limit', [None])

                limit = int(limit[0]) if limit and limit[0] else None

                data = self.player_service.get_track_list(search_query=search, limit=limit)
                return APIResponse.success(data)

            return APIResponse.error("Not Found", 404)
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка обработки плеера: {e}", "error")
            return APIResponse.error(str(e))

    def _handle_plugin_request(self, message: APIMessage) -> Dict[str, Any]:
        """Обработка запросов плагина"""
        try:
            path = message.path

            # GET /api/plugin/status - статус плагина
            if path == '/api/plugin/status':
                status = self.plugin_service.get_status()
                return APIResponse.success(status)

            # GET /api/plugin/presets - все пресеты плагина
            if path == '/api/plugin/presets':
                presets = self.plugin_service.get_all_presets_info()
                return APIResponse.success(presets)

            # GET /api/plugin/current - текущий пресет плагина
            if path == '/api/plugin/current':
                preset = self.plugin_service.get_current_preset_info()
                if preset:
                    return APIResponse.success(preset)
                return APIResponse.error("No preset selected")

            # GET /api/plugin/rack - rack chain плагина
            if path == '/api/plugin/rack':
                rack = self.plugin_service.get_rack_chain()
                if rack:
                    return APIResponse.success(rack)
                return APIResponse.error("Rack chain not available")

            # GET /api/plugin/parameters - параметры плагина
            if path == '/api/plugin/parameters':
                params = self.plugin_service.get_parameters()
                if params:
                    return APIResponse.success(params)
                return APIResponse.error("Parameters not available")

            return APIResponse.error("Not Found", 404)
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка обработки плагина: {e}", "error")
            return APIResponse.error(str(e))

    def _handle_status_request(self, message: APIMessage) -> Dict[str, Any]:
        """Обработка запросов статуса"""
        try:
            path = message.path

            # GET /api/status - полный статус
            if path == '/api/status':
                status = {
                    'preset_catalog': self.preset_catalog.get_statistics(),
                    'player': self.player_service.get_statistics(),
                    'plugin': self.plugin_service.get_status()
                }
                return APIResponse.success(status)

            return APIResponse.error("Not Found", 404)
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка обработки статуса: {e}", "error")
            return APIResponse.error(str(e))

    def _handle_transport_request(self, message: APIMessage) -> Dict[str, Any]:
        """Обработка запросов транспорта"""
        try:
            path = message.path

            # GET /api/transport - состояние транспорта
            if path == '/api/transport':
                # Возвращаем состояние текущего пресета
                current_preset = self.preset_catalog.get_current_preset()
                current_track = self.player_service.get_current_track()

                transport = {
                    'current_preset': current_preset.to_dict() if current_preset else None,
                    'current_track': current_track.to_dict() if current_track else None,
                    'player_state': self.player_service.get_state()
                }
                return APIResponse.success(transport)

            return APIResponse.error("Not Found", 404)
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка обработки транспорта: {e}", "error")
            return APIResponse.error(str(e))

    def start(self) -> bool:
        """Запуск сервера"""
        try:
            with self._lock:
                if self._running:
                    return True

                if self._server is None:
                    if not self.initialize():
                        return False

                self._running = True
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
                return True
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка запуска сервера: {e}", "error")
            return False

    def _run(self) -> None:
        """Запуск сервера в потоке"""
        try:
            while self._running and self._server:
                self._server.handle_request()
        except Exception as e:
            if self.logger:
                self.logger.log_api(f"Ошибка в API сервере: {e}", "error")

    def stop(self) -> None:
        """Остановка сервера"""
        try:
            with self._lock:
                self._running = False
                if self._server:
                    self._server.shutdown()
                    self._server = None
                if self._thread:
                    self._thread.join(timeout=2.0)
                    self._thread = None

                if self.logger:
                    self.logger.log_api("API сервер остановлен", "info")
        except Exception:
            pass

    def is_running(self) -> bool:
        """Проверка запущен ли сервер"""
        try:
            with self._lock:
                return self._running
        except Exception:
            return False

    def get_port(self) -> int:
        """Получение порта"""
        try:
            with self._lock:
                if self._server:
                    return self._server.server_port
                return 5000
        except Exception:
            return 5000