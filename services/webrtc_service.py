"""
WebRTC Service
==============
Optional WebRTC subsystem with lazy import of aiortc.
Graceful degradation if aiortc unavailable.
"""

import asyncio
import json
import time
import uuid
import traceback
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

from core import IService, ServiceHealth, Logger
from core.async_utils import SnapshotStore, run_in_executor


class WebRTCState(Enum):
    """WebRTC connection state"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass
class WebRTCConfig:
    """WebRTC service configuration"""
    enabled: bool = True
    stun_servers: List[str] = field(default_factory=lambda: [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302",
    ])
    turn_servers: List[Dict] = field(default_factory=list)
    ice_candidate_timeout: int = 10
    connection_timeout: int = 30


@dataclass
class WebRTCSession:
    """WebRTC session data"""
    session_id: str
    room_id: str
    peer_id: str
    state: WebRTCState = WebRTCState.DISCONNECTED
    created_at: float = 0
    connected_at: Optional[float] = None
    local_description: Optional[Dict] = None
    remote_description: Optional[Dict] = None
    ice_candidates: List[Dict] = field(default_factory=list)
    remote_ice_candidates: List[Dict] = field(default_factory=list)


class WebRTCService(IService):
    """
    WebRTC service with lazy aiortc import.
    - Graceful degradation if aiortc not available
    - Session-based connections
    - Signaling via Firebase (or custom)
    - Audio track support for streaming
    """
    
    name = "webrtc"
    dependencies = ["firebase"]  # Needs firebase for signaling
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._config = self._load_config()
        self._running = False
        self._webrtc_available = False
        self._aiortc_symbols: Dict = {}
        self._current_session: Optional[WebRTCSession] = None
        self._peer_connection = None
        self._audio_track = None
        self._signaling_callbacks: Dict[str, Callable] = {}
        self._lock = asyncio.Lock()
        self._status_store = SnapshotStore({})
    
    def _load_config(self) -> WebRTCConfig:
        """Load configuration"""
        return WebRTCConfig(
            enabled=self.config_loader.get('webrtc', 'enabled', 'true').lower() == 'true',
            stun_servers=json.loads(self.config_loader.get('webrtc', 'stun_servers', '["stun:stun.l.google.com:19302"]')),
            ice_candidate_timeout=int(self.config_loader.get('webrtc', 'ice_candidate_timeout', '10')),
            connection_timeout=int(self.config_loader.get('webrtc', 'connection_timeout', '30')),
        )
    
    async def start(self) -> bool:
        """Start WebRTC service (lazy import aiortc)"""
        try:
            self.logger.log("Starting WebRTCService...", "info")
            
            if not self._config.enabled:
                self.logger.log("WebRTC disabled in config", "warning")
                return True
            
            # Lazy import aiortc
            success = await self._import_aiortc()
            
            if not success:
                self.logger.log("aiortc unavailable, WebRTC running in degraded mode", "warning")
                self._webrtc_available = False
                # Don't fail - run in degraded mode
                self._running = True
                return True
            
            self._webrtc_available = True
            self._running = True
            self.logger.log("WebRTCService started", "success")
            return True
            
        except Exception as e:
            self.logger.log(f"WebRTCService start failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
            self._webrtc_available = False
            self._running = True  # Degraded mode
            return True
    
    async def stop(self) -> None:
        """Stop WebRTC service"""
        try:
            self.logger.log("Stopping WebRTCService...", "info")
            
            # Close peer connection
            if self._peer_connection:
                await self._close_peer_connection()
            
            self._running = False
            self._webrtc_available = False
            self.logger.log("WebRTCService stopped", "info")
            
        except Exception as e:
            self.logger.log(f"WebRTCService stop error: {e}", "error")
    
    async def healthcheck(self) -> ServiceHealth:
        """Check service health"""
        if not self._running:
            return ServiceHealth.UNHEALTHY
        if not self._webrtc_available:
            return ServiceHealth.DEGRADED
        if self._current_session and self._current_session.state == WebRTCState.CONNECTED:
            return ServiceHealth.HEALTHY
        return ServiceHealth.HEALTHY
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status"""
        return {
            'running': self._running,
            'webrtc_available': self._webrtc_available,
            'config_enabled': self._config.enabled,
            'current_session': {
                'session_id': self._current_session.session_id if self._current_session else None,
                'room_id': self._current_session.room_id if self._current_session else None,
                'peer_id': self._current_session.peer_id if self._current_session else None,
                'state': self._current_session.state.value if self._current_session else None,
                'connected_at': self._current_session.connected_at if self._current_session else None,
            } if self._current_session else None,
        }
    
    async def _import_aiortc(self) -> bool:
        """Lazy import aiortc with timeout"""
        try:
            # Run import in executor to avoid blocking
            def _import():
                from aiortc import (
                    RTCPeerConnection,
                    RTCSessionDescription,
                    RTCIceCandidate,
                    RTCConfiguration,
                    RTCIceServer,
                    MediaStreamTrack,
                    AudioStreamTrack,
                )
                return {
                    'RTCPeerConnection': RTCPeerConnection,
                    'RTCSessionDescription': RTCSessionDescription,
                    'RTCIceCandidate': RTCIceCandidate,
                    'RTCConfiguration': RTCConfiguration,
                    'RTCIceServer': RTCIceServer,
                    'MediaStreamTrack': MediaStreamTrack,
                    'AudioStreamTrack': AudioStreamTrack,
                }
            
            symbols = await asyncio.wait_for(
                run_in_executor(_import),
                timeout=10.0
            )
            
            self._aiortc_symbols = symbols
            self.logger.log("aiortc imported successfully", "success")
            return True
            
        except asyncio.TimeoutError:
            self.logger.log("aiortc import timeout", "error")
            return False
        except ImportError as e:
            self.logger.log(f"aiortc not installed: {e}", "warning")
            return False
        except Exception as e:
            self.logger.log(f"aiortc import error: {e}", "error")
            return False
    
    # ==================== Peer Connection Management ====================
    
    async def create_peer_connection(self, room_id: str, firebase_service) -> Optional[WebRTCSession]:
        """Create a new WebRTC peer connection"""
        if not self._webrtc_available:
            self.logger.log("Cannot create peer connection: aiortc not available", "error")
            return None
        
        try:
            async with self._lock:
                # Close existing connection
                if self._peer_connection:
                    await self._close_peer_connection()
                
                # Create session
                session_id = str(uuid.uuid4())
                peer_id = f"peer_{uuid.uuid4().hex[:8]}"
                
                self._current_session = WebRTCSession(
                    session_id=session_id,
                    room_id=room_id,
                    peer_id=peer_id,
                    state=WebRTCState.CONNECTING,
                    created_at=time.time(),
                )
                
                # Create peer connection
                RTCPeerConnection = self._aiortc_symbols['RTCPeerConnection']
                RTCConfiguration = self._aiortc_symbols['RTCConfiguration']
                RTCIceServer = self._aiortc_symbols['RTCIceServer']
                
                ice_servers = [RTCIceServer(urls=url) for url in self._config.stun_servers]
                for turn in self._config.turn_servers:
                    ice_servers.append(RTCIceServer(**turn))
                
                config = RTCConfiguration(iceServers=ice_servers)
                self._peer_connection = RTCPeerConnection(configuration=config)
                
                # Set up event handlers
                self._setup_peer_connection_handlers(firebase_service)
                
                # Add audio track
                await self._add_audio_track()
                
                self.logger.log(f"Peer connection created: {session_id}", "success")
                return self._current_session
                
        except Exception as e:
            self.logger.log(f"Create peer connection failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
            return None
    
    def _setup_peer_connection_handlers(self, firebase_service) -> None:
        """Set up peer connection event handlers"""
        if not self._peer_connection:
            return
        
        @self._peer_connection.on("iceconnectionstatechange")
        async def on_ice_connection_state_change():
            state = self._peer_connection.iceConnectionState
            self.logger.log(f"ICE connection state: {state}", "info")
            
            if self._current_session:
                if state == "connected":
                    self._current_session.state = WebRTCState.CONNECTED
                    self._current_session.connected_at = time.time()
                elif state in ("failed", "disconnected", "closed"):
                    self._current_session.state = WebRTCState.FAILED
            
            # Notify Firebase
            if firebase_service:
                await firebase_service.update_webrtc_state({
                    'ice_state': state,
                    'timestamp': time.time(),
                })
        
        @self._peer_connection.on("icecandidate")
        async def on_ice_candidate(candidate):
            if candidate:
                candidate_data = {
                    'candidate': candidate.candidate,
                    'sdpMid': candidate.sdpMid,
                    'sdpMLineIndex': candidate.sdpMLineIndex,
                }
                if self._current_session:
                    self._current_session.ice_candidates.append(candidate_data)
                
                # Send via Firebase signaling
                if firebase_service:
                    await firebase_service.update_webrtc_state({
                        'ice_candidate': candidate_data,
                        'timestamp': time.time(),
                    })
        
        @self._peer_connection.on("track")
        def on_track(track):
            self.logger.log(f"Received track: {track.kind}", "info")
            if track.kind == "audio":
                # Handle incoming audio track
                pass
    
    async def _add_audio_track(self) -> None:
        """Add local audio track to peer connection"""
        if not self._peer_connection or not self._webrtc_available:
            return
        
        try:
            AudioStreamTrack = self._aiortc_symbols['AudioStreamTrack']
            
            # Create custom audio track that pulls from audio engine
            class GR7AudioTrack(AudioStreamTrack):
                def __init__(self, audio_service):
                    super().__init__()
                    self.audio_service = audio_service
                
                async def recv(self):
                    # Get audio frame from audio service
                    # This would be implemented with actual audio callback
                    frame = await self._get_audio_frame()
                    return frame
                
                async def _get_audio_frame(self):
                    # Placeholder - would get from audio engine ring buffer
                    import av
                    import numpy as np
                    # Create silent frame for now
                    frame = av.AudioFrame(format='fltp', layout='stereo', samples=960)
                    frame.planes[0].update(np.zeros(960, dtype=np.float32).tobytes())
                    frame.planes[1].update(np.zeros(960, dtype=np.float32).tobytes())
                    frame.sample_rate = 48000
                    frame.time_base = av.time_base
                    return frame
            
            # Note: In real implementation, pass audio_service reference
            self._audio_track = GR7AudioTrack(None)
            self._peer_connection.addTrack(self._audio_track)
            
        except Exception as e:
            self.logger.log(f"Add audio track failed: {e}", "error")
    
    async def create_offer(self) -> Optional[Dict]:
        """Create WebRTC offer"""
        if not self._peer_connection or not self._webrtc_available:
            return None
        
        try:
            offer = await self._peer_connection.createOffer()
            await self._peer_connection.setLocalDescription(offer)
            
            if self._current_session:
                self._current_session.local_description = {
                    'type': offer.type,
                    'sdp': offer.sdp,
                }
            
            return {
                'type': offer.type,
                'sdp': offer.sdp,
            }
            
        except Exception as e:
            self.logger.log(f"Create offer failed: {e}", "error")
            return None
    
    async def create_answer(self, offer: Dict) -> Optional[Dict]:
        """Create WebRTC answer from offer"""
        if not self._peer_connection or not self._webrtc_available:
            return None
        
        try:
            RTCSessionDescription = self._aiortc_symbols['RTCSessionDescription']
            
            remote_desc = RTCSessionDescription(sdp=offer['sdp'], type=offer['type'])
            await self._peer_connection.setRemoteDescription(remote_desc)
            
            if self._current_session:
                self._current_session.remote_description = offer
            
            answer = await self._peer_connection.createAnswer()
            await self._peer_connection.setLocalDescription(answer)
            
            if self._current_session:
                self._current_session.local_description = {
                    'type': answer.type,
                    'sdp': answer.sdp,
                }
            
            return {
                'type': answer.type,
                'sdp': answer.sdp,
            }
            
        except Exception as e:
            self.logger.log(f"Create answer failed: {e}", "error")
            return None
    
    async def set_remote_description(self, description: Dict) -> bool:
        """Set remote description (offer or answer)"""
        if not self._peer_connection or not self._webrtc_available:
            return False
        
        try:
            RTCSessionDescription = self._aiortc_symbols['RTCSessionDescription']
            
            remote_desc = RTCSessionDescription(sdp=description['sdp'], type=description['type'])
            await self._peer_connection.setRemoteDescription(remote_desc)
            
            if self._current_session:
                self._current_session.remote_description = description
            
            return True
            
        except Exception as e:
            self.logger.log(f"Set remote description failed: {e}", "error")
            return False
    
    async def add_ice_candidate(self, candidate: Dict) -> bool:
        """Add ICE candidate"""
        if not self._peer_connection or not self._webrtc_available:
            return False
        
        try:
            RTCIceCandidate = self._aiortc_symbols['RTCIceCandidate']
            
            ice_candidate = RTCIceCandidate(
                candidate=candidate['candidate'],
                sdpMid=candidate.get('sdpMid'),
                sdpMLineIndex=candidate.get('sdpMLineIndex', 0),
            )
            
            await self._peer_connection.addIceCandidate(ice_candidate)
            
            if self._current_session:
                self._current_session.remote_ice_candidates.append(candidate)
            
            return True
            
        except Exception as e:
            self.logger.log(f"Add ICE candidate failed: {e}", "error")
            return False
    
    async def _close_peer_connection(self) -> None:
        """Close peer connection"""
        if self._peer_connection:
            try:
                await self._peer_connection.close()
            except Exception:
                pass
            self._peer_connection = None
        
        self._audio_track = None
        if self._current_session:
            self._current_session.state = WebRTCState.CLOSED
    
    # ==================== Public API ====================
    
    def is_available(self) -> bool:
        return self._webrtc_available
    
    def get_session(self) -> Optional[WebRTCSession]:
        return self._current_session
    
    def get_local_description(self) -> Optional[Dict]:
        return self._current_session.local_description if self._current_session else None
    
    def get_remote_description(self) -> Optional[Dict]:
        return self._current_session.remote_description if self._current_session else None
    
    def get_ice_candidates(self) -> List[Dict]:
        return self._current_session.ice_candidates if self._current_session else []
    
    def get_remote_ice_candidates(self) -> List[Dict]:
        return self._current_session.remote_ice_candidates if self._current_session else []
    
    def register_signaling_callback(self, event: str, callback: Callable) -> None:
        """Register callback for signaling events"""
        self._signaling_callbacks[event] = callback
    
    async def handle_signaling_message(self, message: Dict, firebase_service) -> Optional[Dict]:
        """Handle incoming signaling message"""
        msg_type = message.get('type')
        
        if msg_type == 'offer':
            answer = await self.create_answer(message)
            return {'type': 'answer', 'data': answer}
        
        elif msg_type == 'answer':
            await self.set_remote_description(message)
            return None
        
        elif msg_type == 'ice_candidate':
            await self.add_ice_candidate(message.get('candidate', {}))
            return None
        
        return None


class DummyWebRTCService:
    """Dummy WebRTC service for when aiortc is unavailable"""
    
    name = "webrtc"
    dependencies = ["firebase"]
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._running = False
        self._webrtc_available = False
    
    async def start(self) -> bool:
        self.logger.log("WebRTC: using DummyWebRTCService (aiortc unavailable)", "warning")
        self._running = True
        return True
    
    async def stop(self) -> None:
        self._running = False
    
    async def healthcheck(self) -> ServiceHealth:
        return ServiceHealth.DEGRADED
    
    async def get_status(self) -> Dict[str, Any]:
        return {
            'running': self._running,
            'webrtc_available': False,
            'error': 'aiortc not available',
        }
    
    def is_available(self) -> bool:
        return False