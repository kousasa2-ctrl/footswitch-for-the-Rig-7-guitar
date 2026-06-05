"""
AudioService
============
Production-grade audio service using realtime engine with ASIO support.
Implements IService interface for ServiceManager.
"""

import asyncio
import threading
import traceback
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass

from core import IService, ServiceHealth, Logger
from core.async_utils import SnapshotStore
from audio.realtime_engine import RealtimeAudioEngine, AudioConfig, create_audio_engine
from audio.pedalboard_processor import PedalboardProcessor, ProcessorConfig, create_processor


@dataclass
class AudioServiceConfig:
    """Audio service configuration"""
    sample_rate: int = 48000
    block_size: int = 64
    channels: int = 2
    dtype: str = "float32"
    latency: str = "low"
    device_input: Optional[int] = None
    device_output: Optional[int] = None
    asio_driver: Optional[str] = None
    vst3_path: Optional[str] = None
    use_pedalboard: bool = True
    pedalboard_chain: List[Dict] = None
    bypass: bool = False
    
    def __post_init__(self):
        if self.pedalboard_chain is None:
            self.pedalboard_chain = []


class AudioService(IService):
    """
    Audio service with realtime engine.
    Provides ASIO audio I/O with Guitar Rig 7 VST3 / pedalboard processing.
    """
    
    name = "audio"
    dependencies = []  # No dependencies - core service
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._config = self._load_config()
        self._engine: Optional[RealtimeAudioEngine] = None
        self._processor: Optional[PedalboardProcessor] = None
        self._status_store = SnapshotStore({})
        self._running = False
        self._lock = threading.Lock()
    
    def _load_config(self) -> AudioServiceConfig:
        """Load configuration from config loader"""
        return AudioServiceConfig(
            sample_rate=int(self.config_loader.get('audio', 'sample_rate', '48000')),
            block_size=int(self.config_loader.get('audio', 'buffer_size', '64')),
            channels=int(self.config_loader.get('audio', 'channels', '2')),
            dtype=self.config_loader.get('audio', 'dtype', 'float32'),
            latency=self.config_loader.get('audio', 'latency', 'low'),
            device_input=self._parse_device(self.config_loader.get('audio', 'device_input', '')),
            device_output=self._parse_device(self.config_loader.get('audio', 'device_output', '')),
            asio_driver=self.config_loader.get('audio', 'asio_driver', ''),
            vst3_path=self.config_loader.get('vst3', 'path', ''),
            use_pedalboard=self.config_loader.get('audio', 'use_pedalboard', 'true').lower() == 'true',
            bypass=self.config_loader.get('audio', 'bypass', 'false').lower() == 'true',
        )
    
    def _parse_device(self, value: str) -> Optional[int]:
        """Parse device ID from config"""
        try:
            return int(value) if value else None
        except ValueError:
            return None
    
    async def start(self) -> bool:
        """Start the audio service"""
        try:
            self.logger.log_audio("Starting AudioService...", "info")
            
            # Create engine
            engine_config = {
                'sample_rate': self._config.sample_rate,
                'block_size': self._config.block_size,
                'channels': self._config.channels,
                'dtype': self._config.dtype,
                'latency': self._config.latency,
                'device_input': self._config.device_input,
                'device_output': self._config.device_output,
                'asio_driver': self._config.asio_driver,
            }
            self._engine = create_audio_engine(engine_config, self.logger)
            
            # Initialize engine
            if not self._engine.initialize():
                self.logger.log_audio("Engine initialization failed", "error")
                return False
            
            # Create processor
            processor_config = {
                'vst3_path': self._config.vst3_path,
                'use_pedalboard': self._config.use_pedalboard,
                'pedalboard_chain': self._config.pedalboard_chain,
                'bypass': self._config.bypass,
            }
            self._processor = create_processor(processor_config, self.logger)
            
            # Initialize processor
            if not self._processor.initialize(
                self._config.sample_rate,
                self._config.block_size,
                self._config.channels
            ):
                self.logger.log_audio("Processor initialization failed", "error")
                return False
            
            # Connect processor to engine
            self._engine.set_process_callback(self._processor.process)
            
            # Start engine
            if not self._engine.start():
                self.logger.log_audio("Engine start failed", "error")
                return False
            
            self._running = True
            self.logger.log_audio("AudioService started successfully", "success")
            return True
            
        except Exception as e:
            self.logger.log_audio(f"AudioService start failed: {e}", "error")
            self.logger.log_audio(traceback.format_exc(), "error")
            return False
    
    async def stop(self) -> None:
        """Stop the audio service"""
        try:
            self.logger.log_audio("Stopping AudioService...", "info")
            
            if self._engine:
                self._engine.stop()
                self._engine.shutdown()
                self._engine = None
            
            if self._processor:
                self._processor.shutdown()
                self._processor = None
            
            self._running = False
            self.logger.log_audio("AudioService stopped", "info")
            
        except Exception as e:
            self.logger.log_audio(f"AudioService stop error: {e}", "error")
    
    async def healthcheck(self) -> ServiceHealth:
        """Check service health"""
        try:
            if not self._running or not self._engine:
                return ServiceHealth.UNHEALTHY
            
            status = self._engine.get_status()
            
            if status.state.value == "error":
                return ServiceHealth.UNHEALTHY
            elif status.state.value == "running":
                # Check for underruns/overruns
                if status.buffer_underruns > 10 or status.buffer_overruns > 10:
                    return ServiceHealth.DEGRADED
                return ServiceHealth.HEALTHY
            else:
                return ServiceHealth.DEGRADED
                
        except Exception:
            return ServiceHealth.UNHEALTHY
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status"""
        try:
            status = {}
            
            if self._engine:
                engine_status = self._engine.get_status()
                status['engine'] = {
                    'state': engine_status.state.value,
                    'sample_rate': engine_status.sample_rate,
                    'block_size': engine_status.block_size,
                    'channels': engine_status.channels,
                    'input_device': engine_status.input_device,
                    'output_device': engine_status.output_device,
                    'cpu_load': engine_status.cpu_load,
                    'buffer_underruns': engine_status.buffer_underruns,
                    'buffer_overruns': engine_status.buffer_overruns,
                    'callback_time_ms': engine_status.callback_time_ms,
                    'error': engine_status.error,
                }
                
                # VU meter
                status['vu_meter'] = self._engine.get_vu_meter()
                
                # Waveform (for UI)
                waveform = self._engine.get_waveform(256)
                status['waveform'] = {
                    'left': waveform['left'].tolist(),
                    'right': waveform['right'].tolist(),
                }
            
            if self._processor:
                proc_status = self._processor.get_status()
                status['processor'] = {
                    'initialized': proc_status.initialized,
                    'vst3_loaded': proc_status.vst3_loaded,
                    'pedalboard_active': proc_status.pedalboard_active,
                    'current_preset': proc_status.current_preset,
                    'bypass': proc_status.bypass,
                    'error': proc_status.error,
                }
            
            status['running'] = self._running
            return status
            
        except Exception as e:
            self.logger.log_audio(f"Get status error: {e}", "error")
            return {'error': str(e), 'running': self._running}
    
    def set_bypass(self, bypass: bool) -> None:
        """Set processor bypass"""
        if self._processor:
            self._processor.set_bypass(bypass)
    
    def load_preset(self, preset_path: str) -> bool:
        """Load a preset"""
        if self._processor:
            return self._processor.load_preset(preset_path)
        return False
    
    def get_vu_meter(self) -> Dict[str, float]:
        """Get VU meter levels"""
        if self._engine:
            return self._engine.get_vu_meter()
        return {'left': 0.0, 'right': 0.0, 'peak_left': 0.0, 'peak_right': 0.0, 'clipping': False}
    
    def get_waveform(self, num_samples: int = 512) -> Dict[str, List[float]]:
        """Get waveform data for display"""
        if self._engine:
            waveform = self._engine.get_waveform(num_samples)
            return {
                'left': waveform['left'].tolist(),
                'right': waveform['right'].tolist(),
            }
        return {'left': [0.0] * num_samples, 'right': [0.0] * num_samples}
    
    def reset_peaks(self) -> None:
        """Reset peak meters"""
        if self._engine:
            self._engine.reset_peak_meters()
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate
    
    @property
    def block_size(self) -> int:
        return self._config.block_size
    
    @property
    def latency_ms(self) -> float:
        if self._engine:
            status = self._engine.get_status()
            return (status.block_size / status.sample_rate) * 1000
        return 0.0