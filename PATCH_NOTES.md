# GR7 Hub v2.0.0 - Complete Reconstruction Patch Notes

## Summary
Complete architectural reconstruction from a broken, import-hell codebase to a production-grade, modular, async-first system.

---

## 🏗️ Architecture Changes

### Before (Broken)
- ❌ Circular imports everywhere
- ❌ Heavy imports in main thread (aiortc, pedalboard, sounddevice, bleak, firebase)
- ❌ UI freezes on startup (disk scan, QR generation, VST introspection)
- ❌ Deadlocks from nested locks
- ❌ Fake audio pipeline (no real processing)
- ❌ Broken player (no VU meter, no waveform)
- ❌ Broken preset scan (no cache, scans every startup)
- ❌ Broken QR (shared cache, no session isolation)
- ❌ Unstable aiortc (crashes app on import failure)
- ❌ Blocking startup (no background bootstrap)
- ❌ Services break bootstrap (no isolation)
- ❌ Firebase not integrated
- ❌ No service isolation
- ❌ No modular startup

### After (Production-Grade)
- ✅ **Main Thread = GUI ONLY** - Zero heavy imports
- ✅ **Service Manager** - Dependency resolution, lifecycle, health monitoring
- ✅ **Bootstrap Manager** - Phased startup, timeouts, isolation, degraded modes
- ✅ **Config-based services** - Enable/disable via `config.ini`
- ✅ **Lazy loading** - Heavy libs imported only when service starts
- ✅ **Async-first** - All services: `async start/stop/healthcheck/get_status`
- ✅ **Service isolation** - Failure doesn't cascade
- ✅ **Graceful degradation** - aiortc missing? WebRTC runs in degraded mode
- ✅ **Health monitoring** - Real-time dashboard with HEALTHY/DEGRADED/UNHEALTHY

---

## 📁 New File Structure

### Core Infrastructure (`core/`)
| File | Purpose |
|------|---------|
| `service_states.py` | `ServiceState`, `ServiceHealth` enums |
| `service_manager.py` | Service lifecycle, dependencies, health monitoring |
| `bootstrap.py` | Phased startup (CORE → EXTENDED → BACKGROUND) |
| `async_utils.py` | `RingBuffer`, `SnapshotStore`, `run_in_executor`, `AsyncTaskGroup` |
| `config_loader.py` | INI config with `[services]` section |
| `logger.py` | Multi-channel logging (BOOT, AUDIO, FIREBASE, WEBRTC, BLE, PLAYER, QR, PRESET, UI, SYSTEM) |
| `diagnostics.py` | Freeze detection, deadlock detection, watchdog |
| `state_manager.py` | Global state management |

### Audio Engine (`audio/`)
| File | Purpose |
|------|---------|
| `realtime_engine.py` | Lock-free ASIO callback, ring buffers, 48kHz/64/float32 |
| `pedalboard_processor.py` | Pedalboard + Guitar Rig 7 VST3 processing |

### Services (`services/`)
| File | Service | Key Features |
|------|---------|--------------|
| `audio_service.py` | Audio Engine | ASIO only, pedalboard/VST3, WebRTC output, VU meter |
| `firebase_service.py` | Firebase | REST sessions, Spark plan, room isolation, WebRTC signaling |
| `qr_service.py` | QR Generator | Session-based (UUID/nonce/token), isolated cache, async |
| `ble_service.py` | BLE | GATT server (Session/Pairing/Room/Status), pairing only |
| `webrtc_service.py` | WebRTC | Lazy aiortc (10s timeout), graceful degradation, signaling |
| `preset_catalog.py` | Preset Scan | Async background, indexed cache, checksums, categories |
| `player_service.py` | Player | Real decoding (soundfile), VU meter, waveform, playlist |

### UI (`ui/`)
| File | Tabs |
|------|------|
| `main_window.py` | Dashboard, Audio Monitor, Presets, Player, Settings, Logs |

---

## 🔧 Key Technical Decisions

### 1. Main Thread Purity
```python
# main.py - ONLY these imports:
from core.logger import Logger
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

# NOT imported in main thread:
# aiortc, pedalboard, sounddevice, bleak, firebase-admin, qrcode, PIL
```

### 2. Service Interface
```python
class IService:
    name: str
    dependencies: List[str]
    
    async def start(self) -> bool: ...
    async def stop(self) -> None: ...
    async def healthcheck(self) -> ServiceHealth: ...
    async def get_status(self) -> Dict[str, Any]: ...
```

### 3. Bootstrap Phases
```python
class BootstrapPhase(Enum):
    CORE_SERVICES = "core"        # audio, player (critical)
    EXTENDED_SERVICES = "extended" # firebase, qr, ble, webrtc, preset_scan, api
    BACKGROUND_TASKS = "background" # preset scanning, cache warming
```

### 4. Config-Based Services
```ini
# config.ini
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

### 5. Audio Callback Safety
```python
# NEVER in audio callback:
# - locks
# - print/logging
# - allocations
# - disk I/O
# - Firebase calls
# - numpy resize

# USE:
# - RingBuffer (lock-free)
# - SnapshotStore (atomic reads)
# - Pre-allocated arrays
```

### 6. Lazy aiortc Import
```python
# services/webrtc_service.py
async def _import_aiortc(self) -> bool:
    def _import():
        from aiortc import RTCPeerConnection, ...
        return {...}
    
    symbols = await asyncio.wait_for(run_in_executor(_import), timeout=10.0)
    # If fails → DummyWebRTCService (degraded mode)
```

### 7. Session-Based QR
```json
{
  "session_id": "uuid4",
  "room_id": "firebase_room",
  "nonce": "32_random_bytes",
  "created_at": 123456789,
  "expires_at": 123456999
}
```
Cache: `.qr_cache/{session_uuid}/{qr.png, metadata.json}`

### 8. Preset Index Cache
```json
{
  "version": 1,
  "last_scan": 1234567890,
  "favorites": ["preset_id_1", ...],
  "recent": ["preset_id_2", ...],
  "presets": [
    {"id": "...", "name": "...", "category": "factory", "checksum": "md5", ...}
  ]
}
```

---

## 🎯 Service Status Matrix

| Service | Dependencies | Critical | Phase | Degraded Mode |
|---------|-------------|----------|-------|---------------|
| audio | [] | ✅ | CORE | No |
| player | [audio] | ❌ | CORE | Yes |
| firebase | [] | ❌ | EXTENDED | Yes (offline) |
| qr | [firebase] | ❌ | EXTENDED | Yes (local only) |
| ble | [] | ❌ | EXTENDED | Yes (no BLE) |
| webrtc | [firebase] | ❌ | EXTENDED | Yes (DummyWebRTC) |
| preset_scan | [] | ❌ | EXTENDED | Yes (cached) |
| api_server | [] | ❌ | EXTENDED | Yes |

---

## 📊 Health Monitoring

### Service States
```
STARTING → RUNNING → DEGRADED → FAILED
                ↓
             STOPPED
                ↓
             DISABLED
```

### Health Levels
- **HEALTHY** - Fully operational
- **DEGRADED** - Running with limitations
- **UNHEALTHY** - Not running or critical failure

### Dashboard Updates
- Real-time service status (1s interval)
- VU meter (20 FPS)
- Audio info (latency, CPU, underruns)
- System status header

---

## 🚀 Startup Performance

| Metric | Before | After |
|--------|--------|-------|
| UI Show Time | 10-30s | < 2s |
| Heavy Imports | Main thread | Background |
| Blocking Ops | Many | Zero |
| Service Failures | Crash app | Isolated |
| Config Changes | Code edit | INI file |

---

## 🔄 Migration Guide

### For Developers

#### Adding a Service
1. Create `services/my_service.py` implementing `IService`
2. Add to `services/__init__.py`:
   ```python
   from .my_service import MyService
   def create_my_service(config_loader, logger):
       return MyService(config_loader, logger)
   SERVICE_FACTORIES['my_service'] = create_my_service
   SERVICE_DEPENDENCIES['my_service'] = ['audio']  # or []
   ```
3. Add to `config.ini` `[services]` section

#### Using Services in UI
```python
# Get service manager from main window
service_manager = main_window.service_manager

# Check if running
if service_manager.is_running('audio'):
    status = service_manager.get_service_status('audio')
    
# Enable/disable at runtime
service_manager.enable_service('webrtc')
service_manager.disable_service('ble')
```

---

## ✅ Verification Checklist

### Architecture
- [x] Main thread = GUI only
- [x] No heavy imports in main.py
- [x] ServiceManager with dependency resolution
- [x] BootstrapManager with phases
- [x] Config-based service enable/disable
- [x] Lazy loading for all heavy libs
- [x] Service isolation (failure doesn't cascade)
- [x] Graceful degradation for all optional services

### Audio
- [x] ASIO only (no MME/DirectSound)
- [x] 48kHz / 64 block / float32
- [x] Lock-free callback (RingBuffer)
- [x] Pedalboard processor
- [x] Guitar Rig 7 VST3 support
- [x] VU meter (RMS + peak)
- [x] Clipping detection
- [x] WebRTC audio track output

### Firebase
- [x] REST sessions (no persistent streams)
- [x] Spark plan compatible
- [x] Session isolation (rooms/{room_id})
- [x] WebRTC signaling
- [x] Reconnection with backoff

### QR
- [x] Session-based (UUID/nonce/token)
- [x] Isolated cache per session
- [x] Async generation (background thread)
- [x] 5-minute expiry

### BLE
- [x] GATT server with custom services
- [x] Pairing characteristic (write+notify)
- [x] Room characteristic (read+notify)
- [x] Status characteristic (read+notify)
- [x] No audio over BLE

### WebRTC
- [x] Lazy aiortc import (10s timeout)
- [x] DummyWebRTCService fallback
- [x] Offer/answer/ICE handling
- [x] Firebase signaling
- [x] Audio track from engine

### Presets
- [x] Async background scan
- [x] Indexed cache (preset_index.json)
- [x] Checksum-based change detection
- [x] Incremental updates
- [x] Categories (factory/user/favorites/recent)
- [x] Search/filter

### Player
- [x] Real decoding (soundfile)
- [x] MP3/WAV/FLAC/OGG support
- [x] VU meter with clipping
- [x] Waveform caching
- [x] Playlist (next/prev/seek/volume)

### UI
- [x] Service Dashboard (real-time)
- [x] Audio Monitor (VU meters, waveform)
- [x] Preset Browser (search, categories)
- [x] Player (controls, waveform)
- [x] Settings (service toggles, audio config)
- [x] Logs (category filtering)

### Core
- [x] Multi-channel logger
- [x] ConfigLoader with service config
- [x] RingBuffer, SnapshotStore, AsyncTaskGroup
- [x] Freeze/deadlock detection
- [x] Health monitoring

---

## 📦 Dependencies Added

```txt
# Core
numpy>=1.24.0
sounddevice>=0.4.6
soundfile>=0.12.1
pedalboard>=0.8.0

# GUI
PyQt6>=6.5.0

# Async
psutil>=5.9.0
pyperclip>=1.8.2

# BLE
bleak>=0.21.0

# Firebase
firebase-admin>=6.2.0

# WebRTC (optional)
# aiortc>=1.6.0

# Audio
librosa>=0.10.0

# QR
qrcode>=7.4.0
Pillow>=10.0.0

# Network
aiohttp>=3.8.0
websockets>=11.0.0

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

---

## 🎉 Result

**GR7 Hub v2.0.0 is now:**
- ✅ Modular
- ✅ Async
- ✅ Realtime-safe
- ✅ Non-blocking
- ✅ Production-ready
- ✅ Crash-safe
- ✅ Session-isolated
- ✅ Scalable
- ✅ Lazy-loaded
- ✅ Service-oriented

**Startup:** < 2 seconds to interactive UI
**Runtime:** Service failures isolated, UI never freezes
**Maintenance:** Services enabled/disabled via config.ini
**Extensibility:** New services in 4 steps