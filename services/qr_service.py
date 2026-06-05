"""
QR Service
==========
Session-based QR code generation with isolated cache.
Each session gets unique UUID, nonce, pairing token.
Generation runs in background thread/async task.
"""

import asyncio
import json
import time
import uuid
import secrets
import traceback
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import qrcode
from PyQt6.QtGui import QPixmap

from core import IService, ServiceHealth, Logger
from core.async_utils import SnapshotStore, run_in_executor


class QRCodeType(Enum):
    """Types of QR codes"""
    ROOM_JOIN = "room_join"
    PAIRING = "pairing"
    WEBRTC = "webrtc"


@dataclass
class QRSession:
    """QR session data"""
    session_id: str
    qr_type: QRCodeType
    data: Dict[str, Any]
    created_at: float
    expires_at: float
    pixmap: Optional[QPixmap] = None
    file_path: Optional[str] = None


@dataclass
class QRConfig:
    """QR service configuration"""
    cache_dir: str = ".qr_cache"
    default_size: int = 256
    box_size: int = 10
    border: int = 4
    error_correction: str = "L"  # L, M, Q, H
    session_timeout: int = 3600  # 1 hour
    max_cached_sessions: int = 10


class QRService(IService):
    """
    QR code generation service.
    - Session-based: each run gets unique session
    - Isolated cache per session
    - Background generation (non-blocking)
    - Multiple QR types supported
    """
    
    name = "qr"
    dependencies = ["firebase"]  # Needs firebase for room data
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._config = self._load_config()
        self._cache_dir = Path(self._config.cache_dir)
        self._current_session: Optional[QRSession] = None
        self._running = False
        self._lock = asyncio.Lock()
        self._generation_task: Optional[asyncio.Task] = None
        self._status_store = SnapshotStore({})
    
    def _load_config(self) -> QRConfig:
        """Load configuration"""
        return QRConfig(
            cache_dir=self.config_loader.get('qr', 'cache_dir', '.qr_cache'),
            default_size=int(self.config_loader.get('qr', 'size', '256')),
            box_size=int(self.config_loader.get('qr', 'box_size', '10')),
            border=int(self.config_loader.get('qr', 'border', '4')),
            error_correction=self.config_loader.get('qr', 'error_correction', 'L'),
            session_timeout=int(self.config_loader.get('qr', 'session_timeout', '3600')),
        )
    
    async def start(self) -> bool:
        """Start QR service"""
        try:
            self.logger.log("Starting QRService...", "info")
            
            # Create cache directory
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Clean old cache
            await self._cleanup_old_cache()
            
            self._running = True
            self.logger.log("QRService started", "success")
            return True
            
        except Exception as e:
            self.logger.log(f"QRService start failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
            return False
    
    async def stop(self) -> None:
        """Stop QR service"""
        try:
            self.logger.log("Stopping QRService...", "info")
            
            # Cancel any ongoing generation
            if self._generation_task and not self._generation_task.done():
                self._generation_task.cancel()
                try:
                    await self._generation_task
                except asyncio.CancelledError:
                    pass
            
            self._running = False
            self.logger.log("QRService stopped", "info")
            
        except Exception as e:
            self.logger.log(f"QRService stop error: {e}", "error")
    
    async def healthcheck(self) -> ServiceHealth:
        """Check service health"""
        if not self._running:
            return ServiceHealth.UNHEALTHY
        return ServiceHealth.HEALTHY
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status"""
        return {
            'running': self._running,
            'cache_dir': str(self._cache_dir),
            'current_session': {
                'session_id': self._current_session.session_id if self._current_session else None,
                'qr_type': self._current_session.qr_type.value if self._current_session else None,
                'created_at': self._current_session.created_at if self._current_session else None,
                'expires_at': self._current_session.expires_at if self._current_session else None,
                'has_pixmap': self._current_session.pixmap is not None if self._current_session else False,
                'file_path': self._current_session.file_path if self._current_session else None,
            } if self._current_session else None,
        }
    
    # ==================== QR Generation ====================
    
    async def create_session(self, qr_type: QRCodeType, data: Dict[str, Any]) -> QRSession:
        """Create a new QR session with unique data"""
        async with self._lock:
            session_id = str(uuid.uuid4())
            now = time.time()
            
            # Add session metadata to QR data
            qr_data = {
                'type': qr_type.value,
                'session_id': session_id,
                'nonce': secrets.token_hex(16),
                'timestamp': int(now),
                'expires_at': int(now + self._config.session_timeout),
                **data
            }
            
            session = QRSession(
                session_id=session_id,
                qr_type=qr_type,
                data=qr_data,
                created_at=now,
                expires_at=now + self._config.session_timeout,
            )
            
            self._current_session = session
            
            # Generate QR in background
            self._generation_task = asyncio.create_task(self._generate_qr_async(session))
            
            self.logger.log(f"Created QR session: {session_id} ({qr_type.value})", "info")
            return session
    
    async def _generate_qr_async(self, session: QRSession) -> None:
        """Generate QR code in background thread"""
        try:
            self.logger.log(f"Generating QR for session: {session.session_id}", "info")
            
            # Run CPU-intensive QR generation in executor
            pixmap = await run_in_executor(self._generate_qr_pixmap, session)
            
            if pixmap and not pixmap.isNull():
                session.pixmap = pixmap
                
                # Save to cache
                await self._save_session_cache(session)
                
                self.logger.log(f"QR generated successfully: {session.session_id}", "success")
            else:
                self.logger.log(f"QR generation failed: {session.session_id}", "error")
                
        except Exception as e:
            self.logger.log(f"QR generation error: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
    
    def _generate_qr_pixmap(self, session: QRSession) -> QPixmap:
        """Generate QR pixmap (runs in thread pool)"""
        try:
            # Configure error correction
            error_correction_map = {
                'L': qrcode.constants.ERROR_CORRECT_L,
                'M': qrcode.constants.ERROR_CORRECT_M,
                'Q': qrcode.constants.ERROR_CORRECT_Q,
                'H': qrcode.constants.ERROR_CORRECT_H,
            }
            
            qr = qrcode.QRCode(
                version=1,
                error_correction=error_correction_map.get(self._config.error_correction, qrcode.constants.ERROR_CORRECT_L),
                box_size=self._config.box_size,
                border=self._config.border,
            )
            
            qr.add_data(json.dumps(session.data, separators=(',', ':')))
            qr.make(fit=True)
            
            # Create image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to QPixmap
            import io
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            
            # Scale to default size if needed
            if pixmap.width() != self._config.default_size:
                pixmap = pixmap.scaled(
                    self._config.default_size,
                    self._config.default_size,
                    aspectRatioMode=1,  # KeepAspectRatio
                    transformMode=1  # SmoothTransformation
                )
            
            return pixmap
            
        except Exception as e:
            self.logger.log(f"QR pixmap generation error: {e}", "error")
            return QPixmap()
    
    async def _save_session_cache(self, session: QRSession) -> bool:
        """Save session to isolated cache directory"""
        try:
            session_dir = self._cache_dir / session.session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            
            # Save pixmap
            if session.pixmap and not session.pixmap.isNull():
                pixmap_path = session_dir / "qr.png"
                session.pixmap.save(str(pixmap_path), "PNG")
                session.file_path = str(pixmap_path)
            
            # Save metadata
            metadata = {
                'session_id': session.session_id,
                'qr_type': session.qr_type.value,
                'data': session.data,
                'created_at': session.created_at,
                'expires_at': session.expires_at,
                'file_path': session.file_path,
            }
            
            metadata_path = session_dir / "metadata.json"
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            return True
            
        except Exception as e:
            self.logger.log(f"Save session cache failed: {e}", "error")
            return False
    
    async def _cleanup_old_cache(self) -> None:
        """Clean up expired cache entries"""
        try:
            if not self._cache_dir.exists():
                return
            
            now = time.time()
            sessions = []
            
            for session_dir in self._cache_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                
                metadata_path = session_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        
                        if metadata.get('expires_at', 0) < now:
                            # Expired - remove
                            import shutil
                            shutil.rmtree(session_dir)
                            self.logger.log(f"Removed expired QR cache: {session_dir.name}", "info")
                        else:
                            sessions.append((metadata.get('created_at', 0), session_dir))
                    except Exception:
                        pass
            
            # Limit number of cached sessions
            sessions.sort(key=lambda x: x[0], reverse=True)
            for _, session_dir in sessions[self._config.max_cached_sessions:]:
                import shutil
                shutil.rmtree(session_dir)
                self.logger.log(f"Removed old QR cache (limit): {session_dir.name}", "info")
                
        except Exception as e:
            self.logger.log(f"Cache cleanup error: {e}", "error")
    
    # ==================== Public API ====================
    
    def get_current_session(self) -> Optional[QRSession]:
        """Get current QR session"""
        return self._current_session
    
    def get_current_pixmap(self) -> Optional[QPixmap]:
        """Get current QR pixmap"""
        return self._current_session.pixmap if self._current_session else None
    
    def get_current_qr_data(self) -> Dict[str, Any]:
        """Get current QR data"""
        return self._current_session.data if self._current_session else {}
    
    async def create_room_qr(self, firebase_service) -> QRSession:
        """Create QR for room joining (uses Firebase session)"""
        if not firebase_service:
            raise ValueError("Firebase service required")
        
        qr_data = firebase_service.get_qr_data()
        if not qr_data:
            raise ValueError("No Firebase session data available")
        
        return await self.create_session(QRCodeType.ROOM_JOIN, qr_data)
    
    async def create_pairing_qr(self, pairing_code: str, room_id: str) -> QRSession:
        """Create QR for device pairing"""
        data = {
            'pairing_code': pairing_code,
            'room_id': room_id,
            'url': f"gr7://pair?code={pairing_code}&room={room_id}",
        }
        return await self.create_session(QRCodeType.PAIRING, data)
    
    async def create_webrtc_qr(self, room_id: str, offer: Dict) -> QRSession:
        """Create QR for WebRTC connection"""
        data = {
            'room_id': room_id,
            'offer': offer,
            'url': f"gr7://webrtc?room={room_id}",
        }
        return await self.create_session(QRCodeType.WEBRTC, data)
    
    async def wait_for_generation(self, timeout: float = 5.0) -> bool:
        """Wait for current QR generation to complete"""
        if self._generation_task:
            try:
                await asyncio.wait_for(self._generation_task, timeout=timeout)
                return True
            except asyncio.TimeoutError:
                self.logger.log("QR generation timeout", "warning")
                return False
        return True
    
    def is_generating(self) -> bool:
        """Check if QR is being generated"""
        return self._generation_task is not None and not self._generation_task.done()
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache information"""
        try:
            if not self._cache_dir.exists():
                return {'sessions': 0, 'total_size': 0}
            
            sessions = 0
            total_size = 0
            
            for session_dir in self._cache_dir.iterdir():
                if session_dir.is_dir():
                    sessions += 1
                    for file in session_dir.rglob('*'):
                        if file.is_file():
                            total_size += file.stat().st_size
            
            return {
                'sessions': sessions,
                'total_size': total_size,
                'cache_dir': str(self._cache_dir),
            }
        except Exception:
            return {'sessions': 0, 'total_size': 0}