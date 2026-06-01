# GR7 Hub - Guitar Rig 7 Control Hub

Серверная часть Guitar Rig 7 Hub с VST3 хостингом, каталогом пресетов и мобильным управлением.

## 🎸 Архитектура

```
GR7 Hub/
├── api/                    # API сервер для мобильного клиента
│   ├── __init__.py
│   └── server.py           # REST API endpoints
├── core/                   # Ядро приложения
│   ├── config_loader.py
│   ├── logger.py
│   └── state_manager.py
├── services/               # Сервисы
│   ├── __init__.py
│   ├── plugin_service.py   # VST3 плагин
│   ├── preset_catalog.py   # Каталог пресетов
│   ├── player_service.py   # Backing track player
│   ├── audio_service.py
│   ├── midi_service.py
│   └── webrtc_service.py   # WebRTC соединение
├── vst3/                   # VST3 хостинг
│   ├── host.py
│   └── plugin.py
├── audio/                  # Аудио движок
│   ├── engine.py
│   └── device.py
├── midi/                   # MIDI
│   ├── router.py
│   └── virtual_midi.py
├── webrtc/                 # WebRTC
│   ├── signaling.py
│   └── stream.py
├── utils/                  # Утилиты
│   ├── audio_utils.py
│   └── qr_generator.py
├── main.py                 # GUI приложение
└── config.ini              # Конфигурация
```

## 🚀 Основные возможности

### 1. Загрузка Guitar Rig 7.vst3
- Загружает VST3 плагин из указанного пути
- Проверяет реальное состояние загрузки
- Отдает статус через API

### 2. Каталог пресетов
- Автоматическое сканирование папок с пресетами (.nkp файлы)
- Категории: заводские, пользовательские, избранные, недавние
- Поиск по названию
- Кэширование избранных и недавних пресетов
- API для мобильного клиента

### 3. Backing Track Player
- Воспроизведение MP3, WAV, FLAC, OGG, M4A
- Управление громкостью
- Next/Prev треки
- Статус воспроизведения

### 4. API для мобильного клиента
```
GET    /api/presets              - Список пресетов
GET    /api/presets/current      - Текущий пресет
POST   /api/presets/select       - Выбор пресета
POST   /api/presets/next         - Следующий пресет
POST   /api/presets/prev         - Предыдущий пресет
GET    /api/presets/favorites    - Избранные
GET    /api/presets/recent       - Недавние
GET    /api/presets/rack         - Rack chain
GET    /api/presets/parameters   - Параметры

GET    /api/player/status        - Статус плеера
POST   /api/player/play          - Воспроизвести
POST   /api/player/stop          - Стоп
POST   /api/player/pause         - Пауза
POST   /api/player/next          - Следующий трек
POST   /api/player/prev          - Предыдущий трек
POST   /api/player/volume        - Громкость
GET    /api/player/tracks        - Список треков

GET    /api/plugin/status        - Статус плагина
GET    /api/plugin/presets       - Все пресеты плагина
GET    /api/plugin/current       - Текущий пресет
GET    /api/plugin/rack          - Rack chain
GET    /api/plugin/parameters    - Параметры

GET    /api/status               - Полный статус
GET    /api/transport            - Транспорт
```

### 5. WebRTC соединение
- Создание комнат для подключения
- QR Code для быстрого подключения
- Статус соединения

## 📱 Мобильный клиент

Телефон НЕ хранит всю библиотеку пресетов. Сервер отдает только нужные данные:

1. **Получение каталога**: `GET /api/presets?category=factory&limit=50`
2. **Выбор пресета**: `POST /api/presets/select` с `{"id": "factory_AmpClean"}`
3. **Текущее состояние**: `GET /api/transport`

## 🎨 GUI в стиле Guitar Rig 7

- Темная тема
- Профессиональный дизайн
- Русский интерфейс
- Вкладки: Пресеты, Плеер, Транспорт, Сеть, Настройки

## ⚙️ Конфигурация

```ini
[wifi]
api_key = MY_SECRET_KEY_2026
port = 5000

[gr7]
preset_folder = C:/Users/Саша/Desktop/песни шансик
songs = C:/Users/Саша/Desktop/песни шансик

[paths]
vst3_path = F:/RIG-7-Guitar-Tone-Switch-main/plugins/Guitar Rig 7.vst3
```

## 📦 Установка зависимостей

```bash
pip install -r requirements.txt
```

## 🎯 Как это работает

1. **При запуске**:
   - Загружается VST3 плагин Guitar Rig 7.vst3
   - Сканируются папки с пресетами
   - Загружаются backing tracks
   - Запускается API сервер на порту 5000

2. **На ПК**:
   - Вкладка "Пресеты" показывает список и rack chain
   - Вкладка "Плеер" управляет backing tracks
   - Вкладка "Сеть" создает WebRTC комнату

3. **На телефоне**:
   - Открывает API URL (http://localhost:5000)
   - Получает список пресетов
   - Выбирает preset
   - Управляет плеером

## 🔧 Изменения в коде

### Созданные файлы:
- `services/preset_catalog.py` - Серверный каталог пресетов
- `services/player_service.py` - Backing track player
- `api/server.py` - REST API сервер
- `api/__init__.py` - Интеграция API

### Обновленные файлы:
- `services/plugin_service.py` - Интеграция с PresetCatalog
- `services/webrtc_service.py` - Упрощение, добавлен callback
- `main.py` - Полная переработка GUI
- `services/__init__.py` - Добавлены новые сервисы

## ⚠️ Ограничения VST3 API

Guitar Rig 7 VST3 API может ограничивать доступ к:
- Rack chain (информация может быть недоступна)
- Параметрам (только для некоторых модулей)
- Программному changes (0-127)

Если VST3 API не дает полный доступ, каталог пресетов строится на основе файлов на диске.

## 📝 Логирование

Логи честные, без fake success сообщений:
- `[VST3] Плагин загружен` - только если плагин реально загружен
- `[PLUGIN] Пресет переключен: 5` - только если переключение успешно
- `[API] API сервер запущен на порту 5000` - только если сервер реально запущен

## 🎯 Критические правила соблюдены

✅ Не используется pyautogui
✅ Не используется OpenCV
✅ Не используется поиск PNG
✅ Не используется Win32 click automation
✅ Не используется Ctrl+O
✅ Не используется имитация мышки
✅ Не используются fake success logs
✅ Работает через VST3 host / plugin control / program change

## 📞 API Endpoints

### Пресеты
- `GET /api/presets` - список всех пресетов с пагинацией
- `GET /api/presets/current` - текущий пресет
- `POST /api/presets/select` - выбор пресета
- `POST /api/presets/next` - следующий пресет
- `POST /api/presets/prev` - предыдущий пресет
- `GET /api/presets/favorites` - избранные пресеты
- `GET /api/presets/recent` - недавние пресеты
- `GET /api/presets/rack` - rack chain текущего пресета
- `GET /api/presets/parameters` - параметры текущего пресета

### Плеер
- `GET /api/player/status` - статус плеера
- `POST /api/player/play` - воспроизвести трек
- `POST /api/player/stop` - остановить
- `POST /api/player/pause` - пауза
- `POST /api/player/resume` - продолжить
- `POST /api/player/next` - следующий трек
- `POST /api/player/prev` - предыдущий трек
- `POST /api/player/volume` - громкость
- `GET /api/player/tracks` - список треков

### Плагин
- `GET /api/plugin/status` - статус плагина
- `GET /api/plugin/presets` - все пресеты плагина
- `GET /api/plugin/current` - текущий пресет
- `GET /api/plugin/rack` - rack chain
- `GET /api/plugin/parameters` - параметры

### Система
- `GET /api/status` - полный статус
- `GET /api/transport` - транспорт (пресет + трек)

## 🎮 Запуск

```bash
python main.py
```

После запуска:
1. Проверьте вкладку "Пресеты" - список должен загрузиться
2. Проверьте вкладку "Плеер" - список треков должен загрузиться
3. Проверьте вкладку "Сеть" - нажмите "Создать WebRTC комнату"
4. Проверьте API: `http://localhost:5000/api/status`
