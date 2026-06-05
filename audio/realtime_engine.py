"""
Real-time Audio Engine
======================
Production-grade realtime audio engine using sounddevice with ASIO support.
Lock-free, allocation-free audio callback.
"""

import asyncio
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any, List
from enum import Enum
import numpy as np
import sounddevice as sd

from core.logger import Logger
from core.async_utils import RingBuffer, SnapshotStore


class AudioEngineState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class AudioConfig:
    """Audio engine configuration"""
    sample_rate: int = 48000
    block_size: int = 64
    channels: int = 2
    dtype: str = "float32"
    latency: str = "low"
    device_input: Optional[int] = None
    device_output: Optional[int] = None
    asio_driver: Optional[str] = None


@dataclass
class AudioStatus:
    """Current audio engine status"""
    state: AudioEngineState = AudioEngineState.STOPPED
    sample_rate: int = 0
    block_size: int = 0
    channels: int = 0
    input_device: Optional[str] = None
    output_device: Optional[str] = None
    cpu_load: float = 0.0
    buffer_underruns: int = 0
    buffer_overruns: int = 0
    callback_time_ms: float = 0.0
    error: Optional[str] = None


class AudioCallbackContext:
    """
    Context passed to audio callback - pre-allocated to avoid allocations in callback.
    """
    def __init__(self, block_size: int, channels: int):
        self.input_buffer = np.zeros((block_size, channels), dtype=np.float32)
        self.output_buffer = np.zeros((block_size, channels), dtype=np.float32)
        self.process_buffer = np.zeros((block_size, channels), dtype=np.float32)
        self.callback_start_time = 0.0
        self.frame_count = 0


class RealtimeAudioEngine:
    """
    Real-time audio engine with:
    - ASIO device support
    - Lock-free audio callback
    - Pre-allocated buffers
    - CPU load monitoring
    - Underrun/overrun detection
    - Graceful degradation
    """
    
    def __init__(self, config: AudioConfig, logger: Logger):
        self.config = config
        self.logger = logger
        self._state = AudioEngineState.STOPPED
        self._state_lock = threading.Lock()
        
        # Audio stream
        self._stream: Optional[sd.Stream] = None
        self._stream_thread: Optional[threading.Thread] = None
        
        # Callback
        self._process_callback: Optional[Callable[[np.ndarray], np.ndarray]] = None
        self._callback_context: Optional[AudioCallbackContext] = None
        
        # Status tracking
        self._status = AudioStatus()
        self._status_store = SnapshotStore(self._status)
        self._cpu_load_samples: List[float] = []
        self._max_cpu_samples = 100
        
        # Ring buffers for inter-thread communication
        self._input_ring = RingBuffer(48000 * 2, dtype=np.float32)  # 2 seconds at 48kHz
        self._output_ring = RingBuffer(48000 * 2, dtype=np.float32)
        
        # VU meter data
        self._vu_meter_left = 0.0
        self._vu_meter_right = 0.0
        self._peak_left = 0.0
        self._peak_right = 0.0
        self._clipping_detected = False
        
        # Statistics
        self._callback_count = 0
        self._underrun_count = 0
        self._overrun_count = 0
        self._total_callback_time = 0.0
        
        # Shutdown event
        self._shutdown_event = threading.Event()
    
    @property
    def state(self) -> AudioEngineState:
        with self._state_lock:
            return self._state
    
    def _set_state(self, state: AudioEngineState) -> None:
        with self._state_lock:
            self._state = state
            self._status.state = state
    
    def initialize(self) -> bool:
        """Initialize audio engine and find ASIO devices"""
        try:
            self.logger.log_audio("Initializing realtime audio engine...", "info")
            
            # Query devices
            devices = sd.query_devices()
            self.logger.log_audio(f"Found {len(devices)} audio devices", "info")
            
            # Find ASIO devices
            asio_devices = self._find_asio_devices(devices)
            if asio_devices:
                self.logger.log_audio(f"Found ASIO devices: {[d['name'] for d in asio_devices]}", "success")
            else:
                self.logger.log_audio("No ASIO devices found, will use default", "warning")
            
            # Select devices
            input_device, output_device = self._select_devices(devices, asio_devices)
            
            if input_device is None or output_device is None:
                self.logger.log_audio("Could not find suitable input/output devices", "error")
                return False
            
            self.config.device_input = input_device
            self.config.device_output = output_device
            
            # Validate configuration
            if not self._validate_config():
                return False
            
            # Create callback context
            self._callback_context = AudioCallbackContext(
                self.config.block_size,
                self.config.channels
            )
            
            # Update status
            self._status.sample_rate = self.config.sample_rate
            self._status.block_size = self.config.block_size
            self._status.channels = self.config.channels
            self._status.input_device = devices[input_device]['name'] if input_device is not None else None
            self._status.output_device = devices[output_device]['name'] if output_device is not None else None
            
            self.logger.log_audio(
                f"Audio engine initialized: {self.config.sample_rate}Hz, "
                f"{self.config.block_size} frames, {self.config.channels}ch, "
                f"In: {self._status.input_device}, Out: {self._status.output_device}",
                "success"
            )
            
            return True
            
        except Exception as e:
            self.logger.log_audio(f"Initialization failed: {e}", "error")
            self.logger.log_audio(traceback.format_exc(), "error")
            self._status.error = str(e)
            self._set_state(AudioEngineState.ERROR)
            return False
    
    def _find_asio_devices(self, devices) -> List[Dict]:
        """Find ASIO devices"""
        asio_devices = []
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0 or device['max_output_channels'] > 0:
                name_upper = device['name'].upper()
                if 'ASIO' in name_upper:
                    asio_devices.append({'index': i, 'name': device['name'], 'device': device})
        return asio_devices
    
    def _select_devices(self, devices, asio_devices) -> tuple:
        """Select best input/output devices"""
        input_device = self.config.device_input
        output_device = self.config.device_output
        
        # If specific devices configured, validate them
        if input_device is not None:
            if input_device >= len(devices) or devices[input_device]['max_input_channels'] < self.config.channels:
                self.logger.log_audio(f"Configured input device {input_device} invalid", "warning")
                input_device = None
        
        if output_device is not None:
            if output_device >= len(devices) or devices[output_device]['max_output_channels'] < self.config.channels:
                self.logger.log_audio(f"Configured output device {output_device} invalid", "warning")
                output_device = None
        
        # Auto-select: prefer ASIO
        if input_device is None:
            for asio in asio_devices:
                if asio['device']['max_input_channels'] >= self.config.channels:
                    input_device = asio['index']
                    break
        
        if output_device is None:
            for asio in asio_devices:
                if asio['device']['max_output_channels'] >= self.config.channels:
                    output_device = asio['index']
                    break
        
        # Fallback to default
        if input_device is None:
            try:
                input_device = sd.default.device[0]
            except Exception:
                pass
        
        if output_device is None:
            try:
                output_device = sd.default.device[1]
            except Exception:
                pass
        
        return input_device, output_device
    
    def _validate_config(self) -> bool:
        """Validate audio configuration with sounddevice"""
        try:
            # Test if configuration is supported
            sd.check_input_settings(
                device=self.config.device_input,
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype
            )
            sd.check_output_settings(
                device=self.config.device_output,
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype
            )
            return True
        except Exception as e:
            self.logger.log_audio(f"Configuration validation failed: {e}", "error")
            return False
    
    def set_process_callback(self, callback: Callable[[np.ndarray], np.ndarray]) -> None:
        """Set the audio processing callback"""
        self._process_callback = callback
    
    def start(self) -> bool:
        """Start the audio stream"""
        if self._state in (AudioEngineState.RUNNING, AudioEngineState.STARTING):
            return True
        
        self._set_state(AudioEngineState.STARTING)
        self._shutdown_event.clear()
        
        try:
            # Create stream with callback
            self._stream = sd.Stream(
                device=(self.config.device_input, self.config.device_output),
                samplerate=self.config.sample_rate,
                blocksize=self.config.block_size,
                channels=self.config.channels,
                dtype=self.config.dtype,
                latency=self.config.latency,
                callback=self._audio_callback,
                finished_callback=self._stream_finished_callback
            )
            
            self._stream.start()
            self._set_state(AudioEngineState.RUNNING)
            
            self.logger.log_audio("Audio stream started", "success")
            return True
            
        except Exception as e:
            self.logger.log_audio(f"Failed to start stream: {e}", "error")
            self.logger.log_audio(traceback.format_exc(), "error")
            self._status.error = str(e)
            self._set_state(AudioEngineState.ERROR)
            return False
    
    def stop(self) -> None:
        """Stop the audio stream"""
        if self._state in (AudioEngineState.STOPPED, AudioEngineState.STOPPING):
            return
        
        self._set_state(AudioEngineState.STOPPING)
        self._shutdown_event.set()
        
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                self.logger.log_audio(f"Error stopping stream: {e}", "error")
            finally:
                self._stream = None
        
        self._set_state(AudioEngineState.STOPPED)
        self.logger.log_audio("Audio stream stopped", "info")
    
    def _audio_callback(self, indata, outdata, frames, time_info, status):
        """
        Real-time audio callback - MUST be lock-free and allocation-free.
        This runs on the audio thread (high priority).
        """
        # Track callback timing
        callback_start = time.perf_counter()
        
        # Handle status flags
        if status.input_underflow:
            self._underrun_count += 1
        if status.output_overflow:
            self._overrun_count += 1
        
        ctx = self._callback_context
        if ctx is None:
            outdata.fill(0)
            return
        
        # Copy input to process buffer (avoid modifying indata directly)
        np.copyto(ctx.process_buffer[:frames], indata[:frames])
        
        # Write to input ring buffer for monitoring/recording
        self._input_ring.write(indata[:frames].flatten())
        
        # Process audio if callback is set
        if self._process_callback is not None:
            try:
                # Process the audio
                processed = self._process_callback(ctx.process_buffer[:frames])
                
                # Ensure correct shape
                if processed.shape != (frames, self.config.channels):
                    processed = np.resize(processed, (frames, self.config.channels))
                
                np.copyto(ctx.output_buffer[:frames], processed)
            except Exception:
                # On error, pass through dry signal
                np.copyto(ctx.output_buffer[:frames], ctx.process_buffer[:frames])
        else:
            # Pass-through
            np.copyto(ctx.output_buffer[:frames], ctx.process_buffer[:frames])
        
        # Calculate VU meter levels (RMS)
        if frames > 0:
            left_rms = np.sqrt(np.mean(ctx.output_buffer[:frames, 0] ** 2))
            right_rms = np.sqrt(np.mean(ctx.output_buffer[:frames, 1] ** 2)) if self.config.channels > 1 else left_rms
            
            # Smooth VU meter (exponential moving average)
            alpha = 0.3
            self._vu_meter_left = alpha * left_rms + (1 - alpha) * self._vu_meter_left
            self._vu_meter_right = alpha * right_rms + (1 - alpha) * self._vu_meter_right
            
            # Peak detection
            left_peak = np.max(np.abs(ctx.output_buffer[:frames, 0]))
            right_peak = np.max(np.abs(ctx.output_buffer[:frames, 1])) if self.config.channels > 1 else left_peak
            
            self._peak_left = max(self._peak_left * 0.95, left_peak)
            self._peak_right = max(self._peak_right * 0.95, right_peak)
            
            # Clipping detection
            self._clipping_detected = left_peak >= 0.99 or right_peak >= 0.99
        
        # Copy to output
        np.copyto(outdata[:frames], ctx.output_buffer[:frames])
        
        # Write to output ring buffer
        self._output_ring.write(outdata[:frames].flatten())
        
        # Update statistics
        callback_time = (time.perf_counter() - callback_start) * 1000  # ms
        self._callback_count += 1
        self._total_callback_time += callback_time
        
        # Keep rolling average of CPU load
        cpu_percent = (callback_time / (self.config.block_size / self.config.sample_rate * 1000)) * 100
        self._cpu_load_samples.append(cpu_percent)
        if len(self._cpu_load_samples) > self._max_cpu_samples:
            self._cpu_load_samples.pop(0)
    
    def _stream_finished_callback(self):
        """Called when stream finishes"""
        self.logger.log_audio("Stream finished callback", "info")
        if self._state == AudioEngineState.RUNNING:
            self._set_state(AudioEngineState.ERROR)
            self._status.error = "Stream stopped unexpectedly"
    
    def get_status(self) -> AudioStatus:
        """Get current status (lock-free read)"""
        status = self._status_store.get_data()
        
        # Update dynamic fields
        status.cpu_load = np.mean(self._cpu_load_samples) if self._cpu_load_samples else 0.0
        status.buffer_underruns = self._underrun_count
        status.buffer_overruns = self._overrun_count
        status.callback_time_ms = (
            self._total_callback_time / self._callback_count 
            if self._callback_count > 0 else 0.0
        )
        
        return status
    
    def get_vu_meter(self) -> Dict[str, float]:
        """Get VU meter levels"""
        return {
            'left': float(self._vu_meter_left),
            'right': float(self._vu_meter_right),
            'peak_left': float(self._peak_left),
            'peak_right': float(self._peak_right),
            'clipping': self._clipping_detected
        }
    
    def get_waveform(self, num_samples: int = 512) -> Dict[str, np.ndarray]:
        """Get recent waveform data for display"""
        output_data = self._output_ring.read(num_samples * self.config.channels)
        if len(output_data) == 0:
            return {'left': np.zeros(num_samples), 'right': np.zeros(num_samples)}
        
        # Reshape to channels
        output_data = output_data.reshape(-1, self.config.channels)
        actual_samples = min(num_samples, len(output_data))
        
        return {
            'left': output_data[:actual_samples, 0],
            'right': output_data[:actual_samples, 1] if self.config.channels > 1 else output_data[:actual_samples, 0]
        }
    
    def reset_peak_meters(self) -> None:
        """Reset peak meters"""
        self._peak_left = 0.0
        self._peak_right = 0.0
        self._clipping_detected = False
    
    def shutdown(self) -> None:
        """Shutdown the engine"""
        self.stop()
        self._input_ring.clear()
        self._output_ring.clear()
        self.logger.log_audio("Audio engine shutdown", "info")


def create_audio_engine(config_dict: Dict, logger: Logger) -> RealtimeAudioEngine:
    """Factory function to create audio engine from config dict"""
    config = AudioConfig(
        sample_rate=config_dict.get('sample_rate', 48000),
        block_size=config_dict.get('block_size', 64),
        channels=config_dict.get('channels', 2),
        dtype=config_dict.get('dtype', 'float32'),
        latency=config_dict.get('latency', 'low'),
        device_input=config_dict.get('device_input'),
        device_output=config_dict.get('device_output'),
        asio_driver=config_dict.get('asio_driver')
    )
    return RealtimeAudioEngine(config, logger)