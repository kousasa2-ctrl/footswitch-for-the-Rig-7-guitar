"""
FirebaseService
===============
Firebase service using REST API (no persistent streams).
Short-lived sessions: connect -> write -> disconnect.
Spark plan compatible.
"""

import asyncio
import json
import time
import uuid
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

import requests

from core import IService, ServiceHealth, Logger
from core.async_utils import SnapshotStore


class FirebaseMode(Enum):
    """Firebase operation mode"""
    DISABLED = "disabled"
    REST = "rest"           # Short REST sessions (Spark plan)
    ADMIN_SDK = "admin"     # Admin SDK (requires Blaze plan for streams)


@dataclass
class FirebaseConfig:
    """Firebase service configuration"""
    mode: FirebaseMode = FirebaseMode.REST
    service_account_path: str = "serviceAccountKey.json"
    database_url: str = "https://guitar-remote-app-fab71-default-rtdb.europe-west1.firebasedatabase.app"
    storage_bucket: str = "guitar-remote-app-fab71.appspot.com"
    project_id: str = "guitar-remote-app-fab71"
    api_key: str = ""
    session_timeout: int = 300  # 5 minutes
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class SessionData:
    """Session data structure"""
    session_id: str
    room_id: str
    owner_uid: str
    created_at: float
    expires_at: float
    nonce: str
    pairing_code: str
    status: str = "active"
    clients: List[str] = field(default_factory=list)
    commands: List[Dict] = field(default_factory=list)
    webrtc_offers: Dict = field(default_factory=dict)
    webrtc_answers: Dict = field(default_factory=dict)


class FirebaseService(IService):
    """
    Firebase service using REST API.
    No persistent streams - connect, write, disconnect.
    Session-based isolation.
    """
    
    name = "firebase"
    dependencies = []
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._config = self._load_config()
        self._session: Optional[SessionData] = None
        self._session_file = Path("session_config.json")
        self._running = False
        self._lock = asyncio.Lock()
        self._http_session: Optional[requests.Session] = None
        self._access_token: Optional[str] = None
        self._token_expires: float = 0
    
    def _load_config(self) -> FirebaseConfig:
        """Load configuration"""
        return FirebaseConfig(
            mode=FirebaseMode(self.config_loader.get('firebase', 'mode', 'rest')),
            service_account_path=self.config_loader.get('firebase', 'service_account', 'serviceAccountKey.json'),
            database_url=self.config_loader.get('firebase', 'database_url', 'https://guitar-remote-app-fab71-default-rtdb.europe-west1.firebasedatabase.app'),
            storage_bucket=self.config_loader.get('firebase', 'storage_bucket', 'guitar-remote-app-fab71.appspot.com'),
            project_id=self.config_loader.get('firebase', 'project_id', 'guitar-remote-app-fab71'),
            api_key=self.config_loader.get('firebase', 'api_key', ''),
            session_timeout=int(self.config_loader.get('firebase', 'session_timeout', '300')),
        )
    
    async def start(self) -> bool:
        """Start Firebase service"""
        try:
            self.logger.log("Starting FirebaseService...", "info")
            
            if self._config.mode == FirebaseMode.DISABLED:
                self.logger.log("Firebase disabled in config", "warning")
                return True
            
            # Create HTTP session
            self._http_session = requests.Session()
            self._http_session.headers.update({
                'Content-Type': 'application/json',
                'User-Agent': 'GR7Hub/1.0'
            })
            
            # Try to load existing session
            await self._load_session()
            
            # If no valid session, create new one
            if not self._session or self._is_session_expired():
                await self._create_session()
            
            self._running = True
            self.logger.log("FirebaseService started", "success")
            return True
            
        except Exception as e:
            self.logger.log(f"FirebaseService start failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
            return False
    
    async def stop(self) -> None:
        """Stop Firebase service"""
        try:
            self.logger.log("Stopping FirebaseService...", "info")
            
            # Save session
            await self._save_session()
            
            # Close HTTP session
            if self._http_session:
                self._http_session.close()
                self._http_session = None
            
            self._running = False
            self.logger.log("FirebaseService stopped", "info")
            
        except Exception as e:
            self.logger.log(f"FirebaseService stop error: {e}", "error")
    
    async def healthcheck(self) -> ServiceHealth:
        """Check service health"""
        try:
            if not self._running:
                return ServiceHealth.UNHEALTHY
            
            if self._config.mode == FirebaseMode.DISABLED:
                return ServiceHealth.HEALTHY
            
            # Quick connectivity test
            if self._http_session:
                try:
                    # Test with a simple GET to .info/connected
                    url = f"{self._config.database_url}/.info/connected.json"
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self._http_session.get(url, timeout=5)
                    )
                    if response.status_code == 200:
                        return ServiceHealth.HEALTHY
                except Exception:
                    pass
            
            return ServiceHealth.DEGRADED
            
        except Exception:
            return ServiceHealth.UNHEALTHY
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status"""
        return {
            'running': self._running,
            'mode': self._config.mode.value,
            'project_id': self._config.project_id,
            'database_url': self._config.database_url,
            'session': {
                'session_id': self._session.session_id if self._session else None,
                'room_id': self._session.room_id if self._session else None,
                'status': self._session.status if self._session else None,
                'expires_at': self._session.expires_at if self._session else None,
                'clients_count': len(self._session.clients) if self._session else 0,
            } if self._session else None,
            'token_valid': self._access_token and time.time() < self._token_expires,
        }
    
    # ==================== Session Management ====================
    
    async def _create_session(self) -> bool:
        """Create a new isolated session"""
        try:
            async with self._lock:
                # Generate session data
                session_id = str(uuid.uuid4())
                room_id = f"room_{uuid.uuid4().hex[:12]}"
                nonce = uuid.uuid4().hex
                pairing_code = uuid.uuid4().hex[:8].upper()
                now = time.time()
                
                self._session = SessionData(
                    session_id=session_id,
                    room_id=room_id,
                    owner_uid="gr7_hub_owner",
                    created_at=now,
                    expires_at=now + self._config.session_timeout,
                    nonce=nonce,
                    pairing_code=pairing_code,
                )
                
                # Write to Firebase via REST
                await self._write_session_to_firebase()
                
                # Save locally
                await self._save_session()
                
                self.logger.log(f"Created session: {session_id}, room: {room_id}", "success")
                return True
                
        except Exception as e:
            self.logger.log(f"Create session failed: {e}", "error")
            return False
    
    async def _load_session(self) -> bool:
        """Load session from local file"""
        try:
            if not self._session_file.exists():
                return False
            
            with open(self._session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._session = SessionData(**data)
            self.logger.log(f"Loaded session: {self._session.session_id}", "info")
            return True
            
        except Exception as e:
            self.logger.log(f"Load session failed: {e}", "error")
            return False
    
    async def _save_session(self) -> bool:
        """Save session to local file"""
        try:
            if not self._session:
                return False
            
            data = {
                'session_id': self._session.session_id,
                'room_id': self._session.room_id,
                'owner_uid': self._session.owner_uid,
                'created_at': self._session.created_at,
                'expires_at': self._session.expires_at,
                'nonce': self._session.nonce,
                'pairing_code': self._session.pairing_code,
                'status': self._session.status,
                'clients': self._session.clients,
            }
            
            with open(self._session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
            
        except Exception as e:
            self.logger.log(f"Save session failed: {e}", "error")
            return False
    
    def _is_session_expired(self) -> bool:
        """Check if session is expired"""
        if not self._session:
            return True
        return time.time() >= self._session.expires_at
    
    async def _write_session_to_firebase(self) -> bool:
        """Write session to Firebase via REST"""
        if not self._session or not self._http_session:
            return False
        
        try:
            url = f"{self._config.database_url}/rooms/{self._session.room_id}.json"
            data = {
                'session_id': self._session.session_id,
                'room_id': self._session.room_id,
                'owner_uid': self._session.owner_uid,
                'created_at': self._session.created_at,
                'expires_at': self._session.expires_at,
                'nonce': self._session.nonce,
                'pairing_code': self._session.pairing_code,
                'status': self._session.status,
                'clients': self._session.clients,
                'commands': [],
                'webrtc': {},
                'audio': {},
            }
            
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._http_session.put(url, json=data, timeout=10)
            )
            
            return response.status_code in (200, 201)
            
        except Exception as e:
            self.logger.log(f"Write session to Firebase failed: {e}", "error")
            return False
    
    # ==================== Public API ====================
    
    def get_session_id(self) -> Optional[str]:
        """Get current session ID"""
        return self._session.session_id if self._session else None
    
    def get_room_id(self) -> Optional[str]:
        """Get current room ID"""
        return self._session.room_id if self._session else None
    
    def get_pairing_code(self) -> Optional[str]:
        """Get pairing code for QR"""
        return self._session.pairing_code if self._session else None
    
    def get_nonce(self) -> Optional[str]:
        """Get session nonce"""
        return self._session.nonce if self._session else None
    
    def get_qr_data(self) -> Dict[str, Any]:
        """Get data for QR code generation"""
        if not self._session:
            return {}
        
        return {
            'type': 'gr7_room',
            'session_id': self._session.session_id,
            'room_id': self._session.room_id,
            'nonce': self._session.nonce,
            'pairing_code': self._session.pairing_code,
            'url': f"https://gr7hub.local/join?room={self._session.room_id}&code={self._session.pairing_code}",
            'timestamp': int(self._session.created_at),
            'expires_at': int(self._session.expires_at),
        }
    
    async def send_command(self, command: Dict[str, Any]) -> bool:
        """Send command to room (for mobile app control)"""
        if not self._session or not self._http_session:
            return False
        
        try:
            url = f"{self._config.database_url}/rooms/{self._session.room_id}/commands.json"
            command['timestamp'] = time.time()
            command['id'] = str(uuid.uuid4())
            
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._http_session.post(url, json=command, timeout=5)
            )
            
            return response.status_code in (200, 201)
            
        except Exception as e:
            self.logger.log(f"Send command failed: {e}", "error")
            return False
    
    async def get_commands(self) -> List[Dict]:
        """Get pending commands from room"""
        if not self._session or not self._http_session:
            return []
        
        try:
            url = f"{self._config.database_url}/rooms/{self._session.room_id}/commands.json"
            
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._http_session.get(url, timeout=5)
            )
            
            if response.status_code == 200:
                data = response.json()
                if data:
                    return list(data.values())
            return []
            
        except Exception as e:
            self.logger.log(f"Get commands failed: {e}", "error")
            return []
    
    async def clear_commands(self) -> bool:
        """Clear processed commands"""
        if not self._session or not self._http_session:
            return False
        
        try:
            url = f"{self._config.database_url}/rooms/{self._session.room_id}/commands.json"
            
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._http_session.delete(url, timeout=5)
            )
            
            return response.status_code == 200
            
        except Exception as e:
            self.logger.log(f"Clear commands failed: {e}", "error")
            return False
    
    async def update_webrtc_state(self, webrtc_data: Dict) -> bool:
        """Update WebRTC signaling state"""
        if not self._session or not self._http_session:
            return False
        
        try:
            url = f"{self._config.database_url}/rooms/{self._session.room_id}/webrtc.json"
            
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._http_session.patch(url, json=webrtc_data, timeout=5)
            )
            
            return response.status_code == 200
            
        except Exception as e:
            self.logger.log(f"Update WebRTC state failed: {e}", "error")
            return False
    
    async def get_webrtc_state(self) -> Dict:
        """Get WebRTC signaling state"""
        if not self._session or not self._http_session:
            return {}
        
        try:
            url = f"{self._config.database_url}/rooms/{self._session.room_id}/webrtc.json"
            
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._http_session.get(url, timeout=5)
            )
            
            if response.status_code == 200:
                return response.json() or {}
            return {}
            
        except Exception as e:
            self.logger.log(f"Get WebRTC state failed: {e}", "error")
            return {}
    
    async def register_client(self, client_id: str) -> bool:
        """Register a client in the room"""
        if not self._session:
            return False
        
        if client_id not in self._session.clients:
            self._session.clients.append(client_id)
            await self._write_session_to_firebase()
        
        return True
    
    async def unregister_client(self, client_id: str) -> bool:
        """Unregister a client from the room"""
        if not self._session:
            return False
        
        if client_id in self._session.clients:
            self._session.clients.remove(client_id)
            await self._write_session_to_firebase()
        
        return True
    
    async def extend_session(self, additional_seconds: int = 300) -> bool:
        """Extend session expiration"""
        if not self._session:
            return False
        
        self._session.expires_at = time.time() + additional_seconds
        await self._write_session_to_firebase()
        await self._save_session()
        return True
    
    async def end_session(self) -> bool:
        """End the current session"""
        if not self._session or not self._http_session:
            return False
        
        try:
            # Mark session as ended in Firebase
            url = f"{self._config.database_url}/rooms/{self._session.room_id}/status.json"
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._http_session.patch(url, json={'status': 'ended'}, timeout=5)
            )
            
            # Clear local session
            self._session = None
            if self._session_file.exists():
                self._session_file.unlink()
            
            return response.status_code == 200
            
        except Exception as e:
            self.logger.log(f"End session failed: {e}", "error")
            return False