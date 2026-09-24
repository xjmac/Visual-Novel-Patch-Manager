class VNPatchError(Exception):
    """Base exception class for VNPM errors."""
    pass

class PatchSecurityError(VNPatchError):
    """Raised when a security violation (e.g., path traversal) is detected during extraction."""
    pass

class PatchExtractionError(VNPatchError):
    """Raised when extracting an archive or installer fails."""
    pass

class ProtonExecutionError(VNPatchError):
    """Raised when executing a Windows executable via Proton fails."""
    pass

class BackupError(VNPatchError):
    """Raised when backup creation, verification, or restoration fails."""
    pass

class ConfigError(VNPatchError):
    """Raised when loading or saving configuration fails."""
    pass

class NetworkError(VNPatchError):
    """Raised when external network requests (VNDB, SteamGridDB, SMB) fail."""
    pass

class SteamScanError(VNPatchError):
    """Raised when discovering or parsing Steam libraries and shortcuts fails."""

class ShortcutsVdfError(VNPatchError):
    """Existing shortcuts.vdf could not be parsed; the file was not modified."""
    pass


