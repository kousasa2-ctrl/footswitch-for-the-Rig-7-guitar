"""
Services Package
================
Lightweight service exports - NO heavy imports here.
All services are lazy-loaded via factories.
"""

# Service factories - these are lightweight
from .audio_service import AudioService, AudioServiceConfig, create_audio_engine
from .firebase_service import FirebaseService, FirebaseConfig, FirebaseMode, SessionData
from .qr_service import QRService, QRConfig, QRCodeType, QRSession
from .ble_service import BLEService, BLEConfig, BLEState, BLESession
from .webrtc_service import WebRTCService, WebRTCConfig, WebRTCState, WebRTCSession, DummyWebRTCService
from .preset_catalog import PresetCatalogService, ScanConfig, PresetInfo, PresetIndex, PresetCategory
from .player_service import PlayerService, PlayerConfig, PlayerState, TrackInfo, AudioTrack

__all__ = [
    'AudioService',
    'AudioServiceConfig',
    'create_audio_engine',
    'FirebaseService',
    'FirebaseConfig',
    'FirebaseMode',
    'SessionData',
    'QRService',
    'QRConfig',
    'QRCodeType',
    'QRSession',
    'BLEService',
    'BLEConfig',
    'BLEState',
    'BLESession',
    'WebRTCService',
    'WebRTCConfig',
    'WebRTCState',
    'WebRTCSession',
    'DummyWebRTCService',
    'PresetCatalogService',
    'ScanConfig',
    'PresetInfo',
    'PresetIndex',
    'PresetCategory',
    'PlayerService',
    'PlayerConfig',
    'PlayerState',
    'TrackInfo',
    'AudioTrack',
]

# Service factory functions for bootstrap
def create_audio_service(config_loader, logger):
    """Create AudioService instance"""
    return AudioService(config_loader, logger)

def create_firebase_service(config_loader, logger):
    """Create FirebaseService instance"""
    return FirebaseService(config_loader, logger)

def create_qr_service(config_loader, logger):
    """Create QRService instance"""
    return QRService(config_loader, logger)

def create_ble_service(config_loader, logger):
    """Create BLEService instance"""
    return BLEService(config_loader, logger)

def create_webrtc_service(config_loader, logger):
    """Create WebRTCService instance"""
    return WebRTCService(config_loader, logger)

def create_preset_catalog_service(config_loader, logger):
    """Create PresetCatalogService instance"""
    return PresetCatalogService(config_loader, logger)

def create_player_service(config_loader, logger):
    """Create PlayerService instance"""
    return PlayerService(config_loader, logger)

# Service registry for bootstrap
SERVICE_FACTORIES = {
    'audio': create_audio_service,
    'firebase': create_firebase_service,
    'qr': create_qr_service,
    'ble': create_ble_service,
    'webrtc': create_webrtc_service,
    'preset_scan': create_preset_catalog_service,
    'player': create_player_service,
}

# Service dependencies
SERVICE_DEPENDENCIES = {
    'audio': [],
    'firebase': [],
    'qr': ['firebase'],
    'ble': [],
    'webrtc': ['firebase'],
    'preset_scan': [],
    'player': ['audio'],
}