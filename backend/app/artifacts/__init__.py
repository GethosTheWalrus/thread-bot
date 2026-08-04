"""Artifact storage boundaries; providers must implement this interface."""
from .object_store import ArtifactStore, FilesystemArtifactStore, PostgresArtifactStore
__all__ = ["ArtifactStore", "FilesystemArtifactStore", "PostgresArtifactStore"]
