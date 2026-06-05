"""
Preset Catalog Service
======================
Async preset scanning with indexed cache, checksum validation.
Background scanning, incremental updates.
"""

import asyncio
import hashlib
import json
import os
import time
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, List, Iterator
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
import threading

from core import IService, ServiceHealth, Logger
from core.async_utils import SnapshotStore, run_in_executor, AsyncTaskGroup


class PresetCategory(Enum):
    """Preset categories"""
    FACTORY = "factory"
    USER = "user"
    FAVORITES = "favorites"
    RECENT = "recent"
    SEARCH = "search"


@dataclass
class PresetInfo:
    """Preset information"""
    id: str
    name: str
    category: str
    path: str
    rack_chain: List[Dict[str, Any]] = field(default_factory=list)
    parameters: Dict[str, float] = field(default_factory=dict)
    is_favorite: bool = False
    last_used: Optional[float] = None
    size_bytes: int = 0
    checksum: str = ""
    modified_time: float = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PresetIndex:
    """Preset index for fast lookup"""
    presets: Dict[str, PresetInfo] = field(default_factory=dict)
    categories: Dict[str, List[str]] = field(default_factory=dict)
    favorites: List[str] = field(default_factory=list)
    recent: List[str] = field(default_factory=list)
    last_scan: float = 0
    version: int = 1


@dataclass
class ScanConfig:
    """Scan configuration"""
    paths: List[str] = field(default_factory=list)
    recursive: bool = True
    extensions: List[str] = field(default_factory=lambda: ['.nkp', '.gr7preset', '.json'])
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    checksum_algorithm: str = "md5"


class PresetCatalogService(IService):
    """
    Preset catalog with async scanning and indexed cache.
    - Background scanning with progress
    - Checksum-based change detection
    - Incremental updates
    - Category organization
    - Favorites and recent tracking
    """
    
    name = "preset_scan"
    dependencies = []
    
    def __init__(self, config_loader, logger: Logger):
        self.config_loader = config_loader
        self.logger = logger
        self._config = self._load_config()
        self._index = PresetIndex()
        self._index_file = Path("cache/preset_index.json")
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        self._scan_progress = 0.0
        self._scan_total = 0
        self._scan_current = 0
        self._lock = asyncio.Lock()
        self._status_store = SnapshotStore({})
        self._task_group = AsyncTaskGroup("PresetCatalog")
    
    def _load_config(self) -> ScanConfig:
        """Load scan configuration"""
        # Get preset folder from config
        preset_folder = self.config_loader.get('gr7', 'preset_folder', '')
        
        # Default scan paths
        default_paths = [
            preset_folder,
            "plugins/presets",
            "C:/Program Files/Native Instruments/Guitar Rig 7/Presets",
            "C:/Program Files (x86)/Native Instruments/Guitar Rig 7/Presets",
            os.path.expanduser("~/Documents/Native Instruments/Guitar Rig 7/Presets"),
            os.path.expanduser("~/AppData/Roaming/Native Instruments/Guitar Rig 7/Presets"),
            os.path.expanduser("~/AppData/Local/Native Instruments/Guitar Rig 7/Presets"),
            "C:/ProgramData/Native Instruments/Guitar Rig 7/Presets",
            "C:/Program Files/Common Files/Native Instruments/Guitar Rig 7/Presets",
        ]
        
        # Filter existing paths
        existing_paths = [p for p in default_paths if p and Path(p).exists()]
        
        return ScanConfig(
            paths=existing_paths,
            recursive=True,
            extensions=['.nkp', '.gr7preset', '.json'],
        )
    
    async def start(self) -> bool:
        """Start preset catalog service"""
        try:
            self.logger.log("Starting PresetCatalogService...", "info")
            
            # Load index from cache
            await self._load_index()
            
            # Start background scan if enabled
            if self._config.paths:
                self._scan_task = asyncio.create_task(self._background_scan())
            
            self._running = True
            self.logger.log(f"PresetCatalogService started with {len(self._index.presets)} presets", "success")
            return True
            
        except Exception as e:
            self.logger.log(f"PresetCatalogService start failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
            return False
    
    async def stop(self) -> None:
        """Stop preset catalog service"""
        try:
            self.logger.log("Stopping PresetCatalogService...", "info")
            
            # Cancel scan task
            if self._scan_task and not self._scan_task.done():
                self._scan_task.cancel()
                try:
                    await self._scan_task
                except asyncio.CancelledError:
                    pass
            
            # Save index
            await self._save_index()
            
            await self._task_group.cancel_all()
            
            self._running = False
            self.logger.log("PresetCatalogService stopped", "info")
            
        except Exception as e:
            self.logger.log(f"PresetCatalogService stop error: {e}", "error")
    
    async def healthcheck(self) -> ServiceHealth:
        """Check service health"""
        if not self._running:
            return ServiceHealth.UNHEALTHY
        return ServiceHealth.HEALTHY
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed service status"""
        return {
            'running': self._running,
            'total_presets': len(self._index.presets),
            'categories': {cat: len(ids) for cat, ids in self._index.categories.items()},
            'favorites_count': len(self._index.favorites),
            'recent_count': len(self._index.recent),
            'last_scan': self._index.last_scan,
            'scan_progress': self._scan_progress,
            'scan_total': self._scan_total,
            'scan_current': self._scan_current,
            'scanning': self._scan_task is not None and not self._scan_task.done(),
        }
    
    # ==================== Index Management ====================
    
    async def _load_index(self) -> None:
        """Load preset index from cache file"""
        try:
            if not self._index_file.exists():
                self.logger.log("No preset index cache found", "info")
                return
            
            def _load():
                with open(self._index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data
            
            data = await run_in_executor(_load)
            
            # Reconstruct index
            self._index.last_scan = data.get('last_scan', 0)
            self._index.version = data.get('version', 1)
            self._index.favorites = data.get('favorites', [])
            self._index.recent = data.get('recent', [])
            
            # Reconstruct presets
            for preset_data in data.get('presets', []):
                preset = PresetInfo(**preset_data)
                self._index.presets[preset.id] = preset
                cat = preset.category
                if cat not in self._index.categories:
                    self._index.categories[cat] = []
                if preset.id not in self._index.categories[cat]:
                    self._index.categories[cat].append(preset.id)
            
            self.logger.log(f"Loaded preset index: {len(self._index.presets)} presets", "success")
            
        except Exception as e:
            self.logger.log(f"Load index failed: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
    
    async def _save_index(self) -> None:
        """Save preset index to cache file"""
        try:
            # Ensure cache directory exists
            self._index_file.parent.mkdir(parents=True, exist_ok=True)
            
            def _save():
                data = {
                    'version': self._index.version,
                    'last_scan': self._index.last_scan,
                    'favorites': self._index.favorites,
                    'recent': self._index.recent,
                    'presets': [p.to_dict() for p in self._index.presets.values()],
                }
                with open(self._index_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            
            await run_in_executor(_save)
            self.logger.log("Preset index saved", "info")
            
        except Exception as e:
            self.logger.log(f"Save index failed: {e}", "error")
    
    # ==================== Scanning ====================
    
    async def _background_scan(self) -> None:
        """Background preset scanning"""
        try:
            self.logger.log("Starting background preset scan...", "info")
            await self._scan_all_paths()
            self.logger.log("Background preset scan completed", "success")
        except asyncio.CancelledError:
            self.logger.log("Background scan cancelled", "info")
        except Exception as e:
            self.logger.log(f"Background scan error: {e}", "error")
            self.logger.log(traceback.format_exc(), "error")
    
    async def _scan_all_paths(self) -> None:
        """Scan all configured paths"""
        all_files = []
        
        # Collect all preset files
        for path_str in self._config.paths:
            path = Path(path_str)
            if not path.exists():
                continue
            
            if self._config.recursive:
                for ext in self._config.extensions:
                    all_files.extend(path.rglob(f"*{ext}"))
            else:
                for ext in self._config.extensions:
                    all_files.extend(path.glob(f"*{ext}"))
        
        # Filter by size
        valid_files = []
        for f in all_files:
            try:
                if f.stat().st_size <= self._config.max_file_size:
                    valid_files.append(f)
            except Exception:
                pass
        
        self._scan_total = len(valid_files)
        self._scan_current = 0
        self._scan_progress = 0.0
        
        self.logger.log(f"Scanning {self._scan_total} preset files...", "info")
        
        # Process files in batches
        batch_size = 50
        for i in range(0, len(valid_files), batch_size):
            batch = valid_files[i:i + batch_size]
            await self._process_file_batch(batch)
            
            self._scan_current = min(i + batch_size, self._scan_total)
            self._scan_progress = self._scan_current / self._scan_total if self._scan_total > 0 else 1.0
            
            # Yield control
            await asyncio.sleep(0.01)
        
        self._index.last_scan = time.time()
        await self._save_index()
    
    async def _process_file_batch(self, files: List[Path]) -> None:
        """Process a batch of preset files"""
        for file_path in files:
            try:
                await self._process_preset_file(file_path)
            except Exception as e:
                self.logger.log(f"Error processing {file_path}: {e}", "error")
    
    async def _process_preset_file(self, file_path: Path) -> None:
        """Process a single preset file"""
        try:
            stat = file_path.stat()
            modified_time = stat.st_mtime
            size_bytes = stat.st_size
            
            # Calculate checksum
            checksum = await self._calculate_checksum(file_path)
            
            # Check if already indexed and unchanged
            preset_id = self._generate_preset_id(file_path)
            existing = self._index.presets.get(preset_id)
            
            if existing and existing.checksum == checksum and existing.modified_time == modified_time:
                return  # Unchanged
            
            # Parse preset file
            preset_data = await self._parse_preset_file(file_path)
            
            # Determine category
            category = self._determine_category(file_path)
            
            # Create preset info
            preset = PresetInfo(
                id=preset_id,
                name=preset_data.get('name', file_path.stem),
                category=category,
                path=str(file_path),
                rack_chain=preset_data.get('rack_chain', []),
                parameters=preset_data.get('parameters', {}),
                size_bytes=size_bytes,
                checksum=checksum,
                modified_time=modified_time,
            )
            
            # Update index
            async with self._lock:
                # Remove from old category if exists
                if existing:
                    old_cat = existing.category
                    if old_cat in self._index.categories and preset_id in self._index.categories[old_cat]:
                        self._index.categories[old_cat].remove(preset_id)
                
                # Add to new category
                self._index.presets[preset_id] = preset
                if category not in self._index.categories:
                    self._index.categories[category] = []
                if preset_id not in self._index.categories[category]:
                    self._index.categories[category].append(preset_id)
                    
        except Exception as e:
            self.logger.log(f"Process preset file error {file_path}: {e}", "error")
    
    def _generate_preset_id(self, file_path: Path) -> str:
        """Generate unique preset ID from path"""
        rel_path = str(file_path.relative_to(file_path.anchor)) if file_path.anchor else str(file_path)
        return hashlib.md5(rel_path.encode()).hexdigest()[:16]
    
    async def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate file checksum"""
        def _checksum():
            hasher = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        
        return await run_in_executor(_checksum)
    
    async def _parse_preset_file(self, file_path: Path) -> Dict[str, Any]:
        """Parse preset file (NKP, JSON, etc.)"""
        def _parse():
            try:
                if file_path.suffix.lower() == '.json':
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                elif file_path.suffix.lower() in ('.nkp', '.gr7preset'):
                    # NKP files are typically binary/proprietary
                    # For now, return basic info
                    return {'name': file_path.stem}
            except Exception:
                pass
            return {'name': file_path.stem}
        
        return await run_in_executor(_parse)
    
    def _determine_category(self, file_path: Path) -> str:
        """Determine preset category from path"""
        parts = [p.lower() for p in file_path.parts]
        
        if 'favorite' in parts or 'favorites' in parts:
            return PresetCategory.FAVORITES.value
        if 'recent' in parts:
            return PresetCategory.RECENT.value
        if 'user' in parts or 'user preset' in ' '.join(parts):
            return PresetCategory.USER.value
        if 'factory' in parts:
            return PresetCategory.FACTORY.value
        
        return PresetCategory.FACTORY.value
    
    # ==================== Public API ====================
    
    def get_preset(self, preset_id: str) -> Optional[PresetInfo]:
        """Get preset by ID"""
        return self._index.presets.get(preset_id)
    
    def get_presets(self, category: Optional[str] = None, 
                    search: Optional[str] = None,
                    limit: Optional[int] = None,
                    offset: int = 0) -> List[PresetInfo]:
        """Get presets with filtering"""
        async def _get():
            async with self._lock:
                presets = []
                
                if category:
                    preset_ids = self._index.categories.get(category, [])
                    presets = [self._index.presets[pid] for pid in preset_ids if pid in self._index.presets]
                else:
                    presets = list(self._index.presets.values())
                
                if search:
                    query = search.lower()
                    presets = [p for p in presets if query in p.name.lower()]
                
                # Sort by name
                presets.sort(key=lambda p: p.name.lower())
                
                if limit:
                    presets = presets[offset:offset + limit]
                
                return presets
        
        # Run synchronously for now
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't run async in sync context, return empty
                return []
            return loop.run_until_complete(_get())
        except Exception:
            return []
    
    def get_preset_list(self, category: Optional[str] = None,
                        search: Optional[str] = None,
                        limit: Optional[int] = None,
                        offset: int = 0) -> Dict[str, Any]:
        """Get preset list for API"""
        presets = self.get_presets(category, search, limit, offset)
        
        return {
            'total': len(self._index.presets) if not category else len(self._index.categories.get(category, [])),
            'presets': [p.to_dict() for p in presets],
            'categories': {cat: len(ids) for cat, ids in self._index.categories.items()},
        }
    
    def select_preset(self, preset_id: str) -> bool:
        """Select a preset (add to recent)"""
        if preset_id not in self._index.presets:
            return False
        
        preset = self._index.presets[preset_id]
        preset.last_used = time.time()
        
        # Add to recent
        if preset_id in self._index.recent:
            self._index.recent.remove(preset_id)
        self._index.recent.insert(0, preset_id)
        self._index.recent = self._index.recent[:100]
        
        return True
    
    def toggle_favorite(self, preset_id: str) -> bool:
        """Toggle favorite status"""
        if preset_id not in self._index.presets:
            return False
        
        preset = self._index.presets[preset_id]
        preset.is_favorite = not preset.is_favorite
        
        if preset.is_favorite:
            if preset_id not in self._index.favorites:
                self._index.favorites.append(preset_id)
        else:
            if preset_id in self._index.favorites:
                self._index.favorites.remove(preset_id)
        
        return True
    
    def get_favorites(self) -> List[PresetInfo]:
        """Get favorite presets"""
        return [self._index.presets[pid] for pid in self._index.favorites if pid in self._index.presets]
    
    def get_recent(self, limit: int = 20) -> List[PresetInfo]:
        """Get recent presets"""
        return [self._index.presets[pid] for pid in self._index.recent[:limit] if pid in self._index.presets]
    
    def search_presets(self, query: str, limit: int = 50) -> List[PresetInfo]:
        """Search presets"""
        return self.get_presets(search=query, limit=limit)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get catalog statistics"""
        return {
            'total_presets': len(self._index.presets),
            'categories': {cat: len(ids) for cat, ids in self._index.categories.items()},
            'favorites_count': len(self._index.favorites),
            'recent_count': len(self._index.recent),
            'last_scan': self._index.last_scan,
        }
    
    async def force_rescan(self) -> bool:
        """Force a full rescan"""
        try:
            self.logger.log("Force rescan requested", "info")
            self._index = PresetIndex()  # Clear index
            await self._scan_all_paths()
            return True
        except Exception as e:
            self.logger.log(f"Force rescan failed: {e}", "error")
            return False
    
    def get_scan_progress(self) -> Dict[str, Any]:
        """Get current scan progress"""
        return {
            'progress': self._scan_progress,
            'current': self._scan_current,
            'total': self._scan_total,
            'scanning': self._scan_task is not None and not self._scan_task.done(),
        }