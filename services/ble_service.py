"""
BLE Service
===========
Bluetooth Low Energy service for initial pairing and room join only.
Does NOT stream audio over BLE.
GATT services: Session, Pairing, Room, Status characteristics.
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
from core.async_utils import SnapshotStore


class BLEState(Enum):
    """BLE adapter state"""
    POWERED_OFF = "powered_off"
    POWERED_ON = "powered_on"
    SCANNING = "scanning"
    ADVERTISING = "advertising"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class BLEConfig:
    """BLE service configuration"""
    device_name: str = "GR7 Hub"
    service_uuid: str = "12345678-1234-1234-1234-123456789abc"
    pairing_char_uuid: str = "12345678-1234-1234-1234-123456789abd"
    room_char_uuid: str = "12345678-1234-1234-1234-123456789abe"
    status_char_uuid: str = "12345678-1234-1234-1234-123456789abf"
    advertising_interval: int = 100  # ms
    tx_power: int = 0  # dBm


@dataclass
class BLESession:
    """BLE session data"""
    session_id: str
    pairing_code: str
    room_id: Optional[str] = None
    nonce: str = ""
    created_at: float = 0
    expires_at: float = 0
    connected_clients: List[str] = field(default_factory=list)


class BLEService(IService):
    """
    BLE service for initial pairing and room join.
    - GATT server with custom services
    - Pairing characteristic for secure pairing
    - Room characteristic for room join info
    - Status characteristic for device status
    - Does NOT stream audio over BLE
    """
    
    name = "ble"
    dependencies = []
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._config = self._load_config()
        self._state = BLEState.POWERED_OFF
        self._running = False
        self._current_session: Optional[BLESession] = None
        self._bleak_server = None
        self._advertising = False
        self._lock = asyncio.Lock()
        self._status_store = SnapshotStore({})
        self._callbacks: Dict[str, Callable] = {}
    
    def _load_config(self) -> BLEConfig:
        """Load configuration"""
        return BLEConfig(
            device_name=self.config_loader.get('bluetooth', 'device_name', 'GR7 Hub'),
            advertising_interval=int(self.config_loader.get('bluetooth', 'advertising_interval', '100')),
            tx_power=int(self.config_loader.get('bluetooth', 'tx_power', '0')),
        )
    
    async def start(self) -> bool:
        """Start BLE service"""
        try:
            self.logger.log("Starting BLEService...", "info")
            
            # Try to import bleak
            try:
                import bleak
                from bleak import BleakServer, BleakGATTCharacteristic
                self._bleak_available = True
            except ImportError:
                self.logger.log("bleak not available, BLE disabled", "warning")
                self._bleak_available = False
                self._state = BLEState.ERROR
                return True  # Don't fail bootstrap, just run degraded
            
            # Create GATT server
            self._bleak_server = BleakServer()
            
            # Add custom service
            await self._setup_gatt_services()
            
            # Start advertising
            await self._start_advertising()
            
            self._state = BLEState.ADVERTISING
            self._running = True
            self.logger.log("BLEService started", "success")
            return True
            
        except Exception as e:
            self.logger.log(f"BLEService start failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
            self._state = BLEState.ERROR
            return False
    
    async def stop(self) -> None:
        """Stop BLE service"""
        try:
            self.logger.log("Stopping BLEService...", "info")
            
            if self._bleak_server and self._advertising:
                await self._stop_advertising()
            
            if self._bleak_server:
                await self._bleak_server.disconnect()
                self._bleak_server = None
            
            self._state = BLEState.POWERED_OFF
            self._running = False
            self.logger.log("BLEService stopped", "info")
            
        except Exception as e:
            self.logger.log(f"BLEService stop error: {e}", "error")
    
    async def healthcheck(self) -> ServiceHealth:
        """Check service health"""
        if not self._running:
            return ServiceHealth.UNHEALTHY
        if not self._bleak_available:
            return ServiceHealth.DEGRADED
        if self._state in (BLEState.ADVERTISING, BLEState.CONNECTED):
            return ServiceHealth.HEALTHY
        return ServiceHealth.DEGRADED
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status"""
        return {
            'running': self._running,
            'state': self._state.value,
            'bleak_available': self._bleak_available,
            'advertising': self._advertising,
            'device_name': self._config.device_name,
            'current_session': {
                'session_id': self._current_session.session_id if self._current_session else None,
                'pairing_code': self._current_session.pairing_code if self._current_session else None,
                'room_id': self._current_session.room_id if self._current_session else None,
                'connected_clients': len(self._current_session.connected_clients) if self._current_session else 0,
            } if self._current_session else None,
        }
    
    async def _setup_gatt_services(self) -> None:
        """Setup GATT services and characteristics"""
        if not self._bleak_server:
            return
        
        from bleak import BleakGATTCharacteristic
        
        # Session Service
        session_service = self._bleak_server.add_service(self._config.service_uuid)
        
        # Pairing Characteristic (Write + Notify)
        pairing_char = session_service.add_characteristic(
            self._config.pairing_char_uuid,
            properties=["write", "notify", "read"],
            value=b"",
        )
        pairing_char.on_write = self._on_pairing_write
        
        # Room Characteristic (Read + Notify)
        room_char = session_service.add_characteristic(
            self._config.room_char_uuid,
            properties=["read", "notify"],
            value=b"",
        )
        
        # Status Characteristic (Read + Notify)
        status_char = session_service.add_characteristic(
            self._config.status_char_uuid,
            properties=["read", "notify"],
            value=json.dumps({"state": "ready", "version": "1.0"}).encode(),
        )
    
    async def _start_advertising(self) -> None:
        """Start BLE advertising"""
        if not self._bleak_server:
            return
        
        try:
            await self._bleak_server.start_advertising(
                name=self._config.device_name,
                service_uuids=[self._config.service_uuid],
                interval=self._config.advertising_interval,
            )
            self._advertising = True
            self.logger.log(f"BLE advertising started: {self._config.device_name}", "success")
        except Exception as e:
            self.logger.log(f"BLE advertising failed: {e}", "error")
            self._advertising = False
    
    async def _stop_advertising(self) -> None:
        """Stop BLE advertising"""
        if not self._bleak_server:
            return
        
        try:
            await self._bleak_server.stop_advertising()
            self._advertising = False
            self.logger.log("BLE advertising stopped", "info")
        except Exception as e:
            self.logger.log(f"BLE stop advertising error: {e}", "error")
    
    def _on_pairing_write(self, characteristic, value: bytes) -> None:
        """Handle pairing code write from client"""
        try:
            data = json.loads(value.decode())
            pairing_code = data.get('pairing_code', '')
            client_id = data.get('client_id', str(uuid.uuid4()))
            
            if self._current_session and self._current_session.pairing_code == pairing_code:
                # Valid pairing code
                if client_id not in self._current_session.connected_clients:
                    self._current_session.connected_clients.append(client_id)
                
                # Send room info back
                response = {
                    'status': 'paired',
                    'session_id': self._current_session.session_id,
                    'room_id': self._current_session.room_id,
                    'client_id': client_id,
                }
                characteristic.notify(json.dumps(response).encode())
                
                self.logger.log(f"BLE client paired: {client_id}", "success")
            else:
                # Invalid pairing code
                response = {'status': 'invalid_pairing_code'}
                characteristic.notify(json.dumps(response).encode())
                self.logger.log(f"BLE invalid pairing code from client", "warning")
                
        except Exception as e:
            self.logger.log(f"BLE pairing write error: {e}", "error")
    
    # ==================== Public API ====================
    
    def create_session(self, room_id: Optional[str] = None) -> BLESession:
        """Create a new BLE pairing session"""
        session_id = str(uuid.uuid4())
        pairing_code = uuid.uuid4().hex[:8].upper()
        nonce = uuid.uuid4().hex
        now = time.time()
        
        self._current_session = BLESession(
            session_id=session_id,
            pairing_code=pairing_code,
            room_id=room_id,
            nonce=nonce,
            created_at=now,
            expires_at=now + 300,  # 5 minutes
        )
        
        self.logger.log(f"BLE session created: {session_id}, pairing: {pairing_code}", "info")
        return self._current_session
    
    def get_pairing_code(self) -> Optional[str]:
        """Get current pairing code"""
        return self._current_session.pairing_code if self._current_session else None
    
    def get_session_id(self) -> Optional[str]:
        """Get current session ID"""
        return self._current_session.session_id if self._current_session else None
    
    def set_room_id(self, room_id: str) -> None:
        """Set room ID for current session"""
        if self._current_session:
            self._current_session.room_id = room_id
            # Update room characteristic
            self._update_room_characteristic()
    
    def _update_room_characteristic(self) -> None:
        """Update room characteristic value"""
        if not self._bleak_server or not self._current_session:
            return
        
        try:
            room_char = self._bleak_server.get_characteristic(self._config.room_char_uuid)
            if room_char:
                data = {
                    'room_id': self._current_session.room_id,
                    'session_id': self._current_session.session_id,
                    'nonce': self._current_session.nonce,
                }
                room_char.value = json.dumps(data).encode()
                room_char.notify()
        except Exception as e:
            self.logger.log(f"Update room characteristic error: {e}", "error")
    
    def update_status(self, status: Dict[str, Any]) -> None:
        """Update status characteristic"""
        if not self._bleak_server:
            return
        
        try:
            status_char = self._bleak_server.get_characteristic(self._config.status_char_uuid)
            if status_char:
                status_char.value = json.dumps(status).encode()
                status_char.notify()
        except Exception as e:
            self.logger.log(f"Update status characteristic error: {e}", "error")
    
    def register_callback(self, event: str, callback: Callable) -> None:
        """Register callback for BLE events"""
        self._callbacks[event] = callback
    
    def is_advertising(self) -> bool:
        return self._advertising
    
    def get_connected_clients(self) -> List[str]:
        return self._current_session.connected_clients if self._current_session else []