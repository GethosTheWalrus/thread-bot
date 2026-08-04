from abc import ABC, abstractmethod
from pathlib import Path

class ArtifactStore(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...
    @abstractmethod
    async def get(self, key: str) -> bytes: ...

class PostgresArtifactStore(ArtifactStore):
    """Development adapter. Object storage implementations must preserve this contract."""
    def __init__(self): self._items: dict[str, bytes] = {}
    async def put(self, key, data, content_type): self._items[key] = bytes(data)
    async def delete(self, key): self._items.pop(key, None)
    async def get(self, key): return self._items[key]

class FilesystemArtifactStore(ArtifactStore):
    def __init__(self, root: str): self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
    def _path(self, key):
        path = (self.root / key).resolve()
        if self.root not in path.parents: raise ValueError("artifact key escapes store")
        return path
    async def put(self, key, data, content_type):
        path = self._path(key); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    async def delete(self, key):
        path = self._path(key)
        if path.exists(): path.unlink()
    async def get(self, key): return self._path(key).read_bytes()
