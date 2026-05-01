class SEPError(Exception):
    pass

class ContextValidationError(SEPError):
    pass

class EnforcementBlockedError(SEPError):
    def __init__(self, reason: str, reason_code: str = "BLOCKED"):
        super().__init__(reason)
        self.reason_code = reason_code
