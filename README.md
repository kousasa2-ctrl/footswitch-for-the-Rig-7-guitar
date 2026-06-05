# GR7 Hub - Production-Grade Architecture

## Overview

GR7 Hub is a modular, async-first control center for Guitar Rig 7 with real-time audio processing, Firebase integration, BLE pairing, WebRTC streaming, and QR-based session management.

## Architecture Principles

### Main Thread = GUI ONLY
- **No heavy imports** in main thread (aiortc, pedalboard, sounddevice, bleak, firebase-admin)
- **No blocking operations** in main thread (disk scan, QR generation, VST introspection)
- **UI shows instantly** (< 2 seconds startup)

### Service-Oriented Architecture
Each service is:
- **Independent** - failure doesn't cascade
- **Async-first** - `async start()`, `async stop()`, `async healthcheck()`
- **Configurable** - enable/disable via `config.ini`
- **Observable** - health monitoring, status reporting

### Lazy Loading
- Heavy libraries imported only when service starts
- aiortc imported on-demand in WebRTC service
- pedalboard imported in Audio service
- sounddevice imported in Audio service

## Project Structure

```
GR7 Hub/
├── main.py                    # Entry point - minimal, shows UI instantly
├── config.ini                 # Configuration (services, audio, MIDI, etc.)
├── serviceAccountKey.json     # Firebase credentials
├── requirements.txt           # Dependencies
├── core/                      # Core infrastructure
│   ├── __init__.py           # Exports: Logger, ServiceManager, ServiceState, ServiceHealth
│   ├── logger.py             # Multi-channel logging (BOOT, AUDIO, FIREBASE, etc.)
│   ├── config_loader.py      # INI config with service enable/disable
│   ├── service_states.py     # ServiceState, ServiceHealth enums
│   ├── service_manager.py    # Service lifecycle, dependencies, health monitoring
│   ├── bootstrap.py          # Phased startup with timeouts, isolation
│   ├── async_utils.py        # RingBuffer, SnapshotStore, run_in_executor, AsyncTaskGroup
│   ├── diagnostics.py        # Freeze detection, deadlock detection
│   └── state_manager.py      # Global state management
├── audio/                     # Real-time audio engine
│   ├── __init__.py
│   ├── realtime_engine.py    # Lock-free audio callback, ASIO support
│   └── pedalboard_processor.py # Pedalboard/Guitar Rig VST3 processing
├── services/                  # Modular services
│   ├── __init__.py           # Lightweight exports, factories, registry
│   ├── audio_service.py      # Audio engine service (ASIO, 48kHz, 64 block)
│   ├── firebase_service.py   # Firebase REST sessions (Spark plan friendly)
│   ├── qr_service.py         # Session-based QR codes with isolated cache
│   ├── ble_service.py        # BLE GATT for pairing/room join (no audio)
│   ├── webrtc_service.py     # WebRTC with lazy aiortc, graceful degradation
│   ├── preset_catalog.py     # Async preset scan, indexed cache, checksums
│   └── player_service.py     # Backing track player, VU meter, waveform
├── ui/                        # PyQt6 GUI
│   ├── __init__.py
│   └── main_window.py        # Dashboard, Audio Monitor, Presets, Player, Settings, Logs
├── vst3/                      # VST3 host integration
│   ├── __init__.py
│   ├── host.py
│   └── plugin.py
├── webrtc/                    # WebRTC signaling
│   ├── __init__.py
│   ├── signaling.py
│   └── stream.py
├── api/                       # REST API server
│   ├── __init__.py
│   └── server.py
├── midi/                      # MIDI routing
│   ├── __init__.py
│   ├── router.py
│   └── virtual_midi.py
├── plugins/                   # VST3 plugins & presets
│   ├── Guitar Rig 7.vst3
│   └── presets/
├── utils/                     # Utilities
│   ├── __init__.py
│   ├── audio_utils.py
│   ├── qr_generator.py
│   └── safe_import.py
└── cache/                     # Runtime caches
    ├── preset_index.json
    └── .qr_cache/
```

## Service Configuration

Edit `config.ini` to enable/disable services:

```ini
[services]
audio = true
firebase = false
webrtc = false
ble = false
api_server = true
qr = true
midi = false
preset_scan = true
player = true
vst3 = true
```

## Key Features

### Audio Engine
- **ASIO only** (Windows) - no MME/DirectSound
- **48kHz / 64 samples / float32** - ultra-low latency
- **Lock-free callback** - ring buffers, snapshots
- **Pedalboard + VST3** - Guitar Rig 7 processing
- **WebRTC streaming** - simultaneous local + remote output

### Firebase Integration
- **REST sessions only** - no persistent streams (Spark plan limits)
- **Session isolation** - users can't see each other
- **Room structure**: `rooms/{room_id}/{owner,clients,commands,webrtc,audio}`

### QR System
- **Session-based** - new UUID, nonce, pairing token per launch
- **Isolated cache** - `.qr_cache/{session_uuid}/{qr.png, metadata.json}`
- **Async generation** - never blocks main thread

### BLE
- **GATT services**: Session, Pairing, Room, Status characteristics
- **Pairing only** - no audio streaming over BLE
- **Room join** - exchange Firebase room ID via BLE

### WebRTC
- **Lazy aiortc import** - 10s timeout, graceful degradation
- **Signaling via Firebase** - offer/answer/ICE candidates
- **Audio track** - streams from audio engine ring buffer

### Preset Catalog
- **Async background scan** - doesn't block startup
- **Indexed cache** - `cache/preset_index.json` with checksums
- **Incremental updates** - only changed files re-parsed
- **Categories**: Factory, User, Favorites, Recent

### Player
- **Real audio decoding** - soundfile (MP3, WAV, FLAC, OGG)
- **VU meter** - RMS + peak detection, clipping indicator
- **Waveform** - cached downsampled data
- **Playlist** - next/prev, seek, volume

## Bootstrap Phases

1. **CORE_SERVICES** - Audio, Player (critical)
2. **EXTENDED_SERVICES** - Firebase, QR, BLE, WebRTC, Preset Scan, API Server
3. **BACKGROUND_TASKS** - Preset scanning, cache warming

Each service:
- Has 30s timeout
- Isolated try/except
- Health state tracking
- Degraded mode support

## Service States

```
STARTING → RUNNING → DEGRADED → FAILED
                ↓
             STOPPED
                ↓
             DISABLED
```

## Health Levels

- **HEALTHY** - Fully operational
- **DEGRADED** - Running with limitations (e.g., aiortc unavailable)
- **UNHEALTHY** - Not running or critical failure

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

## Development

### Adding a New Service

1. Create `services/new_service.py` implementing `IService`
2. Add factory to `services/__init__.py`
3. Register in `SERVICE_FACTORIES` and `SERVICE_DEPENDENCIES`
4. Add to `config.ini` `[services]` section

### Service Interface

```python
class IService:
    name: str
    dependencies: List[str]
    
    async def start(self) -> bool: ...
    async def stop(self) -> None: ...
    async def healthcheck(self) -> ServiceHealth: ...
    async def get_status(self) -> Dict[str, Any]: ...
```

## Patch Notes - v2.0.0 (Complete Reconstruction)

### Architecture
- ✅ Complete modular service architecture
- ✅ ServiceManager with dependency resolution
- ✅ BootstrapManager with phased startup
- ✅ Config-based service enable/disable
- ✅ Main thread = GUI only (no heavy imports)

### Audio
- ✅ Real-time engine with sounddevice ASIO
- ✅ Pedalboard processor for Guitar Rig 7
- ✅ Lock-free ring buffers for audio callback
- ✅ VU meter, peak detection, clipping indicator
- ✅ 48kHz / 64 block / float32 configuration

### Firebase
- ✅ REST-based sessions (Spark plan compatible)
- ✅ Session isolation (rooms/{room_id})
- ✅ WebRTC signaling support
- ✅ Reconnection logic with exponential backoff

### QR
- ✅ Session-based QR (UUID, nonce, pairing token)
- ✅ Isolated cache per session
- ✅ Async generation in background thread

### BLE
- ✅ GATT server with custom services
- ✅ Pairing characteristic (write + notify)
- ✅ Room characteristic (read + notify)
- ✅ Status characteristic (read + notify)

### WebRTC
- ✅ Lazy aiortc import (10s timeout)
- ✅ Graceful degradation (DummyWebRTCService)
- ✅ Offer/answer/ICE candidate handling
- ✅ Audio track from engine ring buffer

### Presets
- ✅ Async background scanner
- ✅ Indexed cache with checksums
- ✅ Incremental updates
- ✅ Categories, favorites, recent, search

### Player
- ✅ Real audio decoding (soundfile)
- ✅ VU meter with RMS/peak
- ✅ Waveform caching
- ✅ Playlist controls

### UI
- ✅ Service Dashboard with real-time status
- ✅ Audio Monitor with VU meters
- ✅ Preset Browser with search/filter
- ✅ Player with waveform
- ✅ Settings with service toggles
- ✅ Logs with category filtering

### Core
- ✅ Multi-channel logger (BOOT, AUDIO, FIREBASE, etc.)
- ✅ ConfigLoader with service config
- ✅ Async utilities (RingBuffer, SnapshotStore, TaskGroup)
- ✅ Freeze/deadlock detection
- ✅ Health monitoring

## Requirements

- Python 3.10+
- Windows 10/11 (ASIO support)
- ASIO4ALL or native ASIO driver
- Guitar Rig 7 VST3 installed

## License

MIT License