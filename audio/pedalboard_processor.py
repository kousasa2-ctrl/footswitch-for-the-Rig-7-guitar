"""
Pedalboard Processor
====================
Guitar Rig 7 VST3 and pedalboard processing for realtime audio.
"""

import asyncio
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any, List
from pathlib import Path
import numpy as np

from core.logger import Logger
from core.async_utils import SnapshotStore


@dataclass
class ProcessorConfig:
    """Processor configuration"""
    vst3_path: Optional[str] = None
    use_pedalboard: bool = True
    pedalboard_chain: List[Dict] = None
    bypass: bool = False
    
    def __post_init__(self):
        if self.pedalboard_chain is None:
            self.pedalboard_chain = []


@dataclass
class ProcessorStatus:
    """Processor status"""
    initialized: bool = False
    vst3_loaded: bool = False
    pedalboard_active: bool = False
    current_preset: Optional[str] = None
    bypass: bool = False
    cpu_load: float = 0.0
    error: Optional[str] = None


class PedalboardProcessor:
    """
    Processes audio through Guitar Rig 7 VST3 or pedalboard chain.
    Designed for realtime use - minimal allocations, lock-free reads.
    """
    
    def __init__(self, config: ProcessorConfig, logger: Logger):
        self.config = config
        self.logger = logger
        self._status = ProcessorStatus()
        self._status_store = SnapshotStore(self._status)
        self._lock = threading.Lock()
        
        # VST3 plugin
        self._vst3_plugin = None
        self._vst3_process_func = None
        
        # Pedalboard
        self._pedalboard = None
        self._pedalboard_plugins = []
        
        # Processing buffer (pre-allocated)
        self._process_buffer = None
        self._buffer_size = 0
        self._channels = 0
        
        # Bypass state
        self._bypass = config.bypass
    
    def initialize(self, sample_rate: int, block_size: int, channels: int) -> bool:
        """Initialize processor with audio parameters"""
        try:
            self.logger.log_audio(f"Initializing processor: {sample_rate}Hz, {block_size} frames, {channels}ch", "info")
            
            self._buffer_size = block_size
            self._channels = channels
            self._process_buffer = np.zeros((block_size, channels), dtype=np.float32)
            
            # Try to load VST3 first
            if self.config.vst3_path:
                self._load_vst3(self.config.vst3_path)
            
            # Initialize pedalboard as fallback or primary
            if self.config.use_pedalboard:
                self._init_pedalboard(sample_rate, block_size)
            
            self._status.initialized = True
            self._status.bypass = self._bypass
            self.logger.log_audio("Processor initialized", "success")
            return True
            
        except Exception as e:
            self.logger.log_audio(f"Processor initialization failed: {e}", "error")
            self.logger.log_audio(traceback.format_exc(), "error")
            self._status.error = str(e)
            return False
    
    def _load_vst3(self, path: str) -> bool:
        """Load Guitar Rig 7 VST3 plugin"""
        try:
            self.logger.log_audio(f"Loading VST3: {path}", "info")
            
            # Try to load using vst3 host
            from vst3.host import VST3Host
            
            host = VST3Host()
            if host.load_plugin(path):
                self._vst3_plugin = host
                self._vst3_process_func = host.process
                self._status.vst3_loaded = True
                self.logger.log_audio("VST3 loaded successfully", "success")
                return True
            else:
                self.logger.log_audio("Failed to load VST3 plugin", "warning")
                return False
                
        except ImportError:
            self.logger.log_audio("VST3 host not available", "warning")
            return False
        except Exception as e:
            self.logger.log_audio(f"VST3 load error: {e}", "error")
            return False
    
    def _init_pedalboard(self, sample_rate: int, block_size: int) -> bool:
        """Initialize pedalboard chain"""
        try:
            import pedalboard
            
            self.logger.log_audio("Initializing pedalboard...", "info")
            
            # Create pedalboard from chain config
            plugins = []
            for plugin_config in self.config.pedalboard_chain:
                plugin = self._create_pedalboard_plugin(plugin_config, sample_rate)
                if plugin:
                    plugins.append(plugin)
            
            if plugins:
                self._pedalboard = pedalboard.Pedalboard(plugins)
                self._pedalboard_plugins = plugins
                self._status.pedalboard_active = True
                self.logger.log_audio(f"Pedalboard initialized with {len(plugins)} plugins", "success")
            else:
                self.logger.log_audio("No valid plugins in chain, using pass-through", "warning")
            
            return True
            
        except ImportError:
            self.logger.log_audio("pedalboard not installed", "warning")
            return False
        except Exception as e:
            self.logger.log_audio(f"Pedalboard init error: {e}", "error")
            return False
    
    def _create_pedalboard_plugin(self, config: Dict, sample_rate: int):
        """Create a pedalboard plugin from config"""
        try:
            import pedalboard
            
            plugin_type = config.get('type', '').lower()
            params = config.get('params', {})
            
            # Map plugin types to pedalboard classes
            plugin_map = {
                'gain': pedalboard.Gain,
                'distortion': pedalboard.Distortion,
                'overdrive': pedalboard.Overdrive,
                'chorus': pedalboard.Chorus,
                'phaser': pedalboard.Phaser,
                'flanger': pedalboard.Flanger,
                'reverb': pedalboard.Reverb,
                'delay': pedalboard.Delay,
                'compressor': pedalboard.Compressor,
                'limiter': pedalboard.Limiter,
                'eq': pedalboard.Equalizer,
                'highpass': pedalboard.HighpassFilter,
                'lowpass': pedalboard.LowpassFilter,
                'bandpass': pedalboard.BandpassFilter,
                'noise_gate': pedalboard.NoiseGate,
                'pitch_shift': pedalboard.PitchShift,
                'bitcrush': pedalboard.Bitcrush,
                'clipping': pedalboard.Clipping,
            }
            
            plugin_class = plugin_map.get(plugin_type)
            if not plugin_class:
                self.logger.log_audio(f"Unknown plugin type: {plugin_type}", "warning")
                return None
            
            # Create instance with parameters
            plugin = plugin_class(**params)
            self.logger.log_audio(f"Created plugin: {plugin_type}", "info")
            return plugin
            
        except Exception as e:
            self.logger.log_audio(f"Failed to create plugin {config}: {e}", "error")
            return None
    
    def process(self, input_data: np.ndarray) -> np.ndarray:
        """
        Process audio buffer.
        This is called from the audio callback - must be fast and allocation-free.
        """
        if self._bypass:
            return input_data
        
        frames = input_data.shape[0]
        
        # Ensure process buffer is correct size
        if self._process_buffer.shape[0] < frames:
            self._process_buffer = np.zeros((frames, self._channels), dtype=np.float32)
        
        # Copy input to process buffer
        np.copyto(self._process_buffer[:frames], input_data[:frames])
        
        start_time = time.perf_counter()
        
        try:
            # Try VST3 first
            if self._vst3_process_func is not None:
                processed = self._vst3_process_func(self._process_buffer[:frames])
                if processed is not None and processed.shape == (frames, self._channels):
                    return processed
            
            # Fallback to pedalboard
            if self._pedalboard is not None:
                # Pedalboard expects (channels, frames)
                audio_data = self._process_buffer[:frames].T.copy()
                processed = self._pedalboard(audio_data, sample_rate=48000)
                # Convert back to (frames, channels)
                return processed.T
            
        except Exception as e:
            # On any error, pass through dry
            self.logger.log_audio(f"Processing error: {e}", "error")
        
        # Pass-through
        return input_data
    
    def set_bypass(self, bypass: bool) -> None:
        """Set bypass state"""
        with self._lock:
            self._bypass = bypass
            self._status.bypass = bypass
    
    def set_pedalboard_chain(self, chain: List[Dict]) -> bool:
        """Update pedalboard chain (reinitializes)"""
        with self._lock:
            self.config.pedalboard_chain = chain
            # Would need reinitialize - for now just log
            self.logger.log_audio("Pedalboard chain updated (requires reinit)", "info")
            return True
    
    def load_preset(self, preset_path: str) -> bool:
        """Load a preset (VST3 or pedalboard)"""
        try:
            if self._vst3_plugin and hasattr(self._vst3_plugin, 'load_preset'):
                if self._vst3_plugin.load_preset(preset_path):
                    self._status.current_preset = preset_path
                    self.logger.log_audio(f"Loaded VST3 preset: {preset_path}", "success")
                    return True
            
            # For pedalboard, we'd need to reconstruct chain from preset
            self.logger.log_audio(f"Preset loading not fully implemented: {preset_path}", "warning")
            return False
            
        except Exception as e:
            self.logger.log_audio(f"Preset load error: {e}", "error")
            return False
    
    def get_status(self) -> ProcessorStatus:
        """Get current status"""
        status = self._status_store.get_data()
        return status
    
    def get_cpu_load(self) -> float:
        """Get estimated CPU load"""
        return self._status.cpu_load
    
    def shutdown(self) -> None:
        """Shutdown processor"""
        if self._vst3_plugin:
            try:
                self._vst3_plugin.unload()
            except Exception:
                pass
            self._vst3_plugin = None
            self._vst3_process_func = None
        
        self._pedalboard = None
        self._pedalboard_plugins = []
        self._status.initialized = False
        self.logger.log_audio("Processor shutdown", "info")


def create_processor(config_dict: Dict, logger: Logger) -> PedalboardProcessor:
    """Factory function to create processor from config dict"""
    config = ProcessorConfig(
        vst3_path=config_dict.get('vst3_path'),
        use_pedalboard=config_dict.get('use_pedalboard', True),
        pedalboard_chain=config_dict.get('pedalboard_chain', []),
        bypass=config_dict.get('bypass', False)
    )
    return PedalboardProcessor(config, logger)