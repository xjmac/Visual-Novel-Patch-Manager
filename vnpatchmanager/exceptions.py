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
