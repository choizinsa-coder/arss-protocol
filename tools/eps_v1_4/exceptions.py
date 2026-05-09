ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
class SEPError(Exception):
    pass

class ContextValidationError(SEPError):
    pass

class EnforcementBlockedError(SEPError):
    def __init__(self, reason: str, reason_code: str = "BLOCKED"):
        super().__init__(reason)
        self.reason_code = reason_code
