"""
Player Service
==============
Real backing track player with realtime-safe architecture.
Supports MP3, WAV, FLAC, OGG. VU meter, waveform, position tracking.
"""

import asyncio
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import queue

import numpy as np
import soundfile as sf

from core import IService, ServiceHealth, Logger
from core.async_utils import SnapshotStore, RingBuffer, run_in_executor, AsyncTaskGroup


class PlayerState(Enum):
    """Player states"""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ERROR = "error"


@dataclass
class TrackInfo:
    """Track information"""
    id: str
    name: str
    path: str
    duration: float = 0.0
    size_bytes: int = 0
    format: str = "mp3"
    sample_rate: int = 44100
    channels: int = 2
    is_playing: bool = False
    volume: float = 1.0
    position: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlayerConfig:
    """Player configuration"""
    songs_folder: str = ""
    supported_formats: List[str] = field(default_factory=lambda: ['.mp3', '.wav', '.flac', '.ogg', '.m4a'])
    buffer_size: int = 8192
    preload_seconds: float = 2.0
    crossfade_duration: float = 0.05
    max_tracks: int = 1000


class AudioTrack:
    """Loaded audio track with decoded data"""
    
    def __init__(self, track_info: TrackInfo):
        self.info = track_info
        self.data: Optional[np.ndarray] = None  # (channels, samples)
        self.loaded = False
        self._load_lock = threading.Lock()
    
    def load(self) -> bool:
        """Load audio file into memory"""
        with self._load_lock:
            if self.loaded:
                return True
            
            try:
                data, sr = sf.read(self.info.path, dtype='float32', always_2d=True)
                # soundfile returns (samples, channels), transpose to (channels, samples)
                self.data = data.T
                self.info.sample_rate = sr
                self.info.channels = self.data.shape[0]
                self.info.duration = self.data.shape[1] / sr
                self.loaded = True
                return True
            except Exception as e:
                print(f"Failed to load {self.info.path}: {e}")
                return False
    
    def get_chunk(self, start_sample: int, num_samples: int) -> np.ndarray:
        """Get audio chunk (channels, samples)"""
        if not self.loaded or self.data is None:
            return np.zeros((self.info.channels, num_samples), dtype=np.float32)
        
        end_sample = min(start_sample + num_samples, self.data.shape[1])
        actual_samples = end_sample - start_sample
        
        if actual_samples <= 0:
            return np.zeros((self.info.channels, num_samples), dtype=np.float32)
        
        chunk = self.data[:, start_sample:end_sample]
        
        # Pad if needed
        if actual_samples < num_samples:
            padding = np.zeros((self.info.channels, num_samples - actual_samples), dtype=np.float32)
            chunk = np.concatenate([chunk, padding], axis=1)
        
        return chunk


class PlayerService(IService):
    """
    Backing track player with realtime-safe architecture.
    - Lock-free audio callback via ring buffer
    - Background loading/decoding
    - VU meter, waveform, position tracking
    - Playlist management
    """
    
    name = "player"
    dependencies = ["audio"]  # Needs audio engine for output
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._config = self._load_config()
        self._running = False
        self._tracks: Dict[str, AudioTrack] = {}
        self._current_track_id: Optional[str] = None
        self._state = PlayerState.STOPPED
        self._volume = 1.0
        self._position = 0.0  # seconds
        self._duration = 0.0
        self._sample_position = 0  # samples
        self._sample_rate = 44100
        self._channels = 2
        
        # Playback thread
        self._playback_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._track_queue: queue.Queue = queue.Queue()
        
        # Ring buffer for audio output (lock-free)
        self._output_buffer = RingBuffer(44100 * 10, dtype=np.float32)  # 10 seconds
        
        # VU meter
        self._vu_left = 0.0
        self._vu_right = 0.0
        self._peak_left = 0.0
        self._peak_right = 0.0
        self._clipping = False
        
        # Waveform cache
        self._waveform_cache: Dict[str, Dict[str, np.ndarray]] = {}
        
        # Status
        self._status_store = SnapshotStore({})
        self._lock = threading.Lock()
        self._task_group = AsyncTaskGroup("PlayerService")
        
        # Callbacks
        self._on_track_end: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None
    
    def _load_config(self) -> PlayerConfig:
        """Load configuration"""
        songs_folder = self.config_loader.get('gr7', 'songs', '')
        if not songs_folder:
            songs_folder = self.config_loader.get('paths', 'songs', '')
        
        return PlayerConfig(
            songs_folder=songs_folder,
        )
    
    async def start(self) -> bool:
        """Start player service"""
        try:
            self.logger.log("Starting PlayerService...", "info")
            
            # Load tracks from folder
            if self._config.songs_folder:
                await self._load_tracks(self._config.songs_folder)
            
            # Start playback thread
            self._stop_event.clear()
            self._pause_event.clear()
            self._playback_thread = threading.Thread(
                target=self._playback_loop,
                daemon=True,
                name="PlayerPlayback"
            )
            self._playback_thread.start()
            
            self._running = True
            self.logger.log(f"PlayerService started with {len(self._tracks)} tracks", "success")
            return True
            
        except Exception as e:
            self.logger.log(f"PlayerService start failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
            return False
    
    async def stop(self) -> None:
        """Stop player service"""
        try:
            self.logger.log("Stopping PlayerService...", "info")
            
            self._stop_event.set()
            self._pause_event.set()
            
            if self._playback_thread and self._playback_thread.is_alive():
                self._playback_thread.join(timeout=2.0)
            
            self._running = False
            self.logger.log("PlayerService stopped", "info")
            
        except Exception as e:
            self.logger.log(f"PlayerService stop error: {e}", "error")
    
    async def healthcheck(self) -> ServiceHealth:
        """Check service health"""
        if not self._running:
            return ServiceHealth.UNHEALTHY
        return ServiceHealth.HEALTHY
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status"""
        with self._lock:
            current_track = self._tracks.get(self._current_track_id) if self._current_track_id else None
            
            return {
                'running': self._running,
                'state': self._state.value,
                'current_track': current_track.info.to_dict() if current_track else None,
                'volume': self._volume,
                'position': self._position,
                'duration': self._duration,
                'total_tracks': len(self._tracks),
                'vu_meter': {
                    'left': self._vu_left,
                    'right': self._vu_right,
                    'peak_left': self._peak_left,
                    'peak_right': self._peak_right,
                    'clipping': self._clipping,
                },
            }
    
    # ==================== Track Management ====================
    
    async def _load_tracks(self, folder: str) -> None:
        """Load tracks from folder"""
        try:
            folder_path = Path(folder)
            if not folder_path.exists():
                self.logger.log(f"Songs folder not found: {folder_path}", "warning")
                return
            
            new_tracks = {}
            
            for ext in self._config.supported_formats:
                for file_path in folder_path.rglob(f"*{ext}"):
                    if len(new_tracks) >= self._config.max_tracks:
                        break
                    
                    track_id = f"track_{uuid.uuid4().hex[:12]}"
                    if track_id in new_tracks:
                        continue
                    
                    try:
                        stat = file_path.stat()
                        size_bytes = stat.st_size
                        fmt = ext.lstrip('.')
                        
                        # Quick probe for duration
                        duration = 0.0
                        try:
                            info = sf.info(str(file_path))
                            duration = info.duration
                        except Exception:
                            pass
                        
                        track_info = TrackInfo(
                            id=track_id,
                            name=file_path.stem,
                            path=str(file_path),
                            duration=duration,
                            size_bytes=size_bytes,
                            format=fmt,
                        )
                        
                        new_tracks[track_id] = AudioTrack(track_info)
                        
                    except Exception as e:
                        self.logger.log(f"Error adding track {file_path}: {e}", "error")
            
            with self._lock:
                self._tracks.update(new_tracks)
            
            self.logger.log(f"Loaded {len(new_tracks)} tracks", "info")
            
        except Exception as e:
            self.logger.log(f"Load tracks error: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
    
    def get_track(self, track_id: str) -> Optional[TrackInfo]:
        """Get track info"""
        with self._lock:
            track = self._tracks.get(track_id)
            return track.info if track else None
    
    def get_all_tracks(self) -> List[TrackInfo]:
        """Get all tracks"""
        with self._lock:
            return [t.info for t in self._tracks.values()]
    
    def get_track_list(self, search: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """Get track list for API"""
        with self._lock:
            tracks = list(self._tracks.values())
        
        if search:
            query = search.lower()
            tracks = [t for t in tracks if query in t.info.name.lower()]
        
        if limit:
            tracks = tracks[:limit]
        
        return {
            'total': len(self._tracks),
            'tracks': [t.info.to_dict() for t in tracks],
        }
    
    # ==================== Playback Control ====================
    
    def play_track(self, track_id: str) -> bool:
        """Play a specific track"""
        with self._lock:
            if track_id not in self._tracks:
                self.logger.log(f"Track not found: {track_id}", "error")
                return False
            
            track = self._tracks[track_id]
            
            # Load track if not loaded
            if not track.loaded:
                if not track.load():
                    self.logger.log(f"Failed to load track: {track_id}", "error")
                    return False
            
            # Stop current
            self._stop_unlocked()
            
            # Set new track
            self._current_track_id = track_id
            self._sample_position = 0
            self._position = 0.0
            self._duration = track.info.duration
            self._sample_rate = track.info.sample_rate
            self._channels = track.info.channels
            self._state = PlayerState.PLAYING
            self._pause_event.clear()
            
            # Queue for playback thread
            self._track_queue.put(track_id)
        
        self.logger.log(f"Playing track: {track_id}", "info")
        return True
    
    def _stop_unlocked(self) -> None:
        """Internal stop (must hold lock)"""
        self._state = PlayerState.STOPPED
        self._stop_event.set()
        self._position = 0.0
        self._duration = 0.0
        self._sample_position = 0
    
    def stop(self) -> None:
        """Stop playback"""
        with self._lock:
            self._stop_unlocked()
        
        # Clear queue
        while not self._track_queue.empty():
            try:
                self._track_queue.get_nowait()
            except queue.Empty:
                break
        
        self.logger.log("Playback stopped", "info")
    
    def pause(self) -> None:
        """Pause playback"""
        with self._lock:
            if self._state == PlayerState.PLAYING:
                self._state = PlayerState.PAUSED
                self._pause_event.set()
        self.logger.log("Playback paused", "info")
    
    def resume(self) -> None:
        """Resume playback"""
        with self._lock:
            if self._state == PlayerState.PAUSED:
                self._state = PlayerState.PLAYING
                self._pause_event.clear()
        self.logger.log("Playback resumed", "info")
    
    def set_volume(self, volume: float) -> None:
        """Set volume (0.0 - 1.0)"""
        with self._lock:
            self._volume = max(0.0, min(1.0, volume))
    
    def get_volume(self) -> float:
        """Get volume"""
        with self._lock:
            return self._volume
    
    def seek(self, position: float) -> None:
        """Seek to position (seconds)"""
        with self._lock:
            if self._current_track_id and self._duration > 0:
                self._position = max(0.0, min(position, self._duration))
                self._sample_position = int(self._position * self._sample_rate)
    
    def next_track(self) -> Optional[str]:
        """Play next track"""
        with self._lock:
            tracks = list(self._tracks.values())
            if not tracks:
                return None
            
            if self._current_track_id:
                try:
                    idx = next(i for i, t in enumerate(tracks) if t.info.id == self._current_track_id)
                    next_idx = (idx + 1) % len(tracks)
                    next_id = tracks[next_idx].info.id
                except (StopIteration, ValueError):
                    next_id = tracks[0].info.id
            else:
                next_id = tracks[0].info.id
        
        self.play_track(next_id)
        return next_id
    
    def prev_track(self) -> Optional[str]:
        """Play previous track"""
        with self._lock:
            tracks = list(self._tracks.values())
            if not tracks:
                return None
            
            if self._current_track_id:
                try:
                    idx = next(i for i, t in enumerate(tracks) if t.info.id == self._current_track_id)
                    prev_idx = (idx - 1) % len(tracks)
                    prev_id = tracks[prev_idx].info.id
                except (StopIteration, ValueError):
                    prev_id = tracks[-1].info.id
            else:
                prev_id = tracks[-1].info.id
        
        self.play_track(prev_id)
        return prev_id
    
    def get_current_track(self) -> Optional[TrackInfo]:
        """Get current track"""
        with self._lock:
            if self._current_track_id:
                track = self._tracks.get(self._current_track_id)
                return track.info if track else None
        return None
    
    def get_state(self) -> Dict[str, Any]:
        """Get player state (non-blocking snapshot)"""
        with self._lock:
            current_track = self._tracks.get(self._current_track_id) if self._current_track_id else None
            return {
                'state': self._state.value,
                'current_track': current_track.info.to_dict() if current_track else None,
                'volume': self._volume,
                'position': self._position,
                'duration': self._duration,
                'total_tracks': len(self._tracks),
                'vu_meter': {
                    'left': self._vu_left,
                    'right': self._vu_right,
                    'peak_left': self._peak_left,
                    'peak_right': self._peak_right,
                    'clipping': self._clipping,
                },
            }
    
    def get_waveform(self, track_id: str, num_points: int = 1000) -> Dict[str, List[float]]:
        """Get waveform data for track (cached)"""
        if track_id in self._waveform_cache:
            cached = self._waveform_cache[track_id]
            return {
                'left': cached['left'].tolist(),
                'right': cached['right'].tolist(),
            }
        
        track = self._tracks.get(track_id)
        if not track or not track.loaded:
            return {'left': [0.0] * num_points, 'right': [0.0] * num_points}
        
        # Generate waveform (downsample)
        data = track.data
        if data is None:
            return {'left': [0.0] * num_points, 'right': [0.0] * num_points}
        
        # Downsample to num_points
        total_samples = data.shape[1]
        step = max(1, total_samples // num_points)
        
        left = data[0, ::step][:num_points]
        right = data[1, ::step][:num_points] if data.shape[0] > 1 else left
        
        # Pad if needed
        if len(left) < num_points:
            left = np.pad(left, (0, num_points - len(left)))
            right = np.pad(right, (0, num_points - len(right)))
        
        # Cache
        self._waveform_cache[track_id] = {'left': left, 'right': right}
        
        return {
            'left': left.tolist(),
            'right': right.tolist(),
        }
    
    def get_vu_meter(self) -> Dict[str, float]:
        """Get VU meter levels"""
        with self._lock:
            return {
                'left': self._vu_left,
                'right': self._vu_right,
                'peak_left': self._peak_left,
                'peak_right': self._peak_right,
                'clipping': self._clipping,
            }
    
    def reset_peaks(self) -> None:
        """Reset peak meters"""
        with self._lock:
            self._peak_left = 0.0
            self._peak_right = 0.0
            self._clipping = False
    
    # ==================== Playback Loop ====================
    
    def _playback_loop(self) -> None:
        """Main playback loop (runs in separate thread)"""
        while not self._stop_event.is_set():
            try:
                # Get next track from queue
                try:
                    track_id = self._track_queue.get(timeout=0.1)
                except queue.Empty:
                    # Update position periodically
                    self._update_position()
                    continue
                
                with self._lock:
                    if track_id not in self._tracks:
                        continue
                    
                    track = self._tracks[track_id]
                    self._current_track_id = track_id
                    self._sample_position = 0
                    self._position = 0.0
                    self._duration = track.info.duration
                    self._sample_rate = track.info.sample_rate
                    self._channels = track.info.channels
                    self._state = PlayerState.PLAYING
                    self._pause_event.clear()
                
                # Play track
                self._play_track(track)
                
                # Track ended - auto next
                with self._lock:
                    if self._state == PlayerState.PLAYING and not self._stop_event.is_set():
                        # Find next track
                        tracks = list(self._tracks.values())
                        if tracks:
                            try:
                                idx = next(i for i, t in enumerate(tracks) if t.info.id == track_id)
                                next_idx = (idx + 1) % len(tracks)
                                next_id = tracks[next_idx].info.id
                                self._track_queue.put(next_id)
                            except (StopIteration, ValueError):
                                pass
                
            except Exception as e:
                self.logger.log(f"Playback loop error: {e}", "error")
                self.logger.log(traceback.format_exc(), "error")
                break
    
    def _play_track(self, track: AudioTrack) -> None:
        """Play a single track to completion"""
        if not track.loaded or track.data is None:
            return
        
        data = track.data  # (channels, samples)
        total_samples = data.shape[1]
        chunk_samples = self._config.buffer_size
        
        while self._sample_position < total_samples and not self._stop_event.is_set():
            # Handle pause
            if self._pause_event.is_set():
                time.sleep(0.01)
                continue
            
            # Get chunk
            end_pos = min(self._sample_position + chunk_samples, total_samples)
            chunk = data[:, self._sample_position:end_pos]
            actual_samples = chunk.shape[1]
            
            if actual_samples == 0:
                break
            
            # Apply volume
            chunk = chunk * self._volume
            
            # Update VU meter
            self._update_vu_meter(chunk)
            
            # Write to output buffer (for audio engine to consume)
            # Interleave channels for output
            if self._channels == 2:
                interleaved = np.empty(actual_samples * 2, dtype=np.float32)
                interleaved[0::2] = chunk[0]
                interleaved[1::2] = chunk[1]
            else:
                interleaved = chunk[0]
            
            self._output_buffer.write(interleaved)
            
            # Update position
            self._sample_position += actual_samples
            self._position = self._sample_position / self._sample_rate
            
            # Small sleep to prevent CPU spinning
            time.sleep(0.001)
    
    def _update_vu_meter(self, chunk: np.ndarray) -> None:
        """Update VU meter from audio chunk"""
        if chunk.size == 0:
            return
        
        # RMS levels
        left_rms = np.sqrt(np.mean(chunk[0] ** 2)) if chunk.shape[0] > 0 else 0.0
        right_rms = np.sqrt(np.mean(chunk[1] ** 2)) if chunk.shape[0] > 1 else left_rms
        
        # Smooth VU meter
        alpha = 0.3
        with self._lock:
            self._vu_left = alpha * left_rms + (1 - alpha) * self._vu_left
            self._vu_right = alpha * right_rms + (1 - alpha) * self._vu_right
            
            # Peak detection
            left_peak = np.max(np.abs(chunk[0])) if chunk.shape[0] > 0 else 0.0
            right_peak = np.max(np.abs(chunk[1])) if chunk.shape[0] > 1 else left_peak
            
            self._peak_left = max(self._peak_left * 0.95, left_peak)
            self._peak_right = max(self._peak_right * 0.95, right_peak)
            
            self._clipping = left_peak >= 0.99 or right_peak >= 0.99
    
    def _update_position(self) -> None:
        """Update position (called periodically)"""
        with self._lock:
            if self._state == PlayerState.PLAYING and self._current_track_id:
                track = self._tracks.get(self._current_track_id)
                if track and track.loaded and track.data is not None:
                    # Position is updated in _play_track
                    pass
    
    def get_output_buffer(self) -> RingBuffer:
        """Get output ring buffer for audio engine"""
        return self._output_buffer
    
    def set_callbacks(self, on_track_end: Callable = None, on_state_change: Callable = None) -> None:
        """Set callbacks"""
        self._on_track_end = on_track_end
        self._on_state_change = on_state_change
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get player statistics"""
        with self._lock:
            return {
                'total_tracks': len(self._tracks),
                'current_track': self._current_track_id,
                'state': self._state.value,
                'volume': self._volume,
            }