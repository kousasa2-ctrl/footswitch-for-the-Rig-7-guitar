# GR7 Hub - Complete Rebuild Task Plan

## Phase 1: Core Infrastructure
- [ ] Create `config/services.json` - service enable/disable configuration
- [ ] Create `core/service_manager.py` - ServiceManager with IService interface
- [ ] Create `core/bootstrap.py` - Safe bootstrap with timeout, health states, degraded mode
- [ ] Create `core/service_states.py` - Service state enums (STARTING, RUNNING, DEGRADED, FAILED, STOPPED, DISABLED)
- [ ] Update `core/__init__.py` - Export new core modules
- [ ] Create `core/async_utils.py` - Async utilities, lock-free queues, ring buffers

## Phase 2: Audio Engine (Complete Rewrite)
- [ ] Create `services/audio_service.py` - New AudioService with real ASIO support
- [ ] Create `audio/realtime_engine.py` - Real-time safe audio engine using sounddevice
- [ ] Create `audio/asio_manager.py` - ASIO device management
- [ ] Create `audio/pedalboard_processor.py` - Pedalboard/Guitar Rig VST3 processing
- [ ] Create `audio/ring_buffer.py` - Lock-free ring buffer for audio data
- [ ] Create `audio/vu_meter.py` - VU meter and audio analysis

## Phase 3: Service Implementations
- [ ] Rewrite `services/firebase_service.py` - REST-based sessions, no persistent streams
- [ ] Create `services/ble_service.py` - BLE GATT service for pairing only
- [ ] Rewrite `services/webrtc_service.py` - Lazy aiortc, graceful degradation
- [ ] Rewrite `services/preset_catalog.py` - Async scan, indexed cache, checksum validation
- [ ] Rewrite `services/player_service.py` - Real audio playback with VU meter
- [ ] Create `services/qr_service.py` - Session-based QR with isolated cache
- [ ] Create `services/midi_service.py` - MIDI routing service

## Phase 4: Configuration & Startup
- [ ] Create `config/services.json` - Service enable/disable config
- [ ] Rewrite `main.py` - Minimal, shows UI instantly, background bootstrap
- [ ] Create `core/config_manager.py` - Unified config management
- [ ] Update `services/__init__.py` - Lightweight, no heavy imports

## Phase 5: UI & Monitoring
- [ ] Create `ui/service_dashboard.py` - Service health dashboard
- [ ] Update `ui/main_window.py` - Integrate service dashboard
- [ ] Add realtime metrics: RTT, jitter, packet loss, bitrate, CPU, latency
- [ ] Add VU meter, waveform, peak indicator, clipping detector

## Phase 6: Health & Safety
- [ ] Create `core/health_monitor.py` - Service health monitoring
- [ ] Create `core/watchdog.py` - Enhanced freeze detection
- [ ] Create `core/crash_recovery.py` - Crash recovery mechanisms
- [ ] Add structured logging channels: [BOOT], [AUDIO], [FIREBASE], [WEBRTC], [BLE], [PLAYER], [QR], [PRESET]

## Phase 7: Testing & Validation
- [ ] Verify startup < 2 seconds
- [ ] Verify UI shows instantly
- [ ] Verify service isolation (one service crash doesn't affect others)
- [ ] Verify audio engine works with ASIO
- [ ] Verify QR sessions are isolated
- [ ] Verify offline mode works
- [ ] Verify all services can be enabled/disabled via config