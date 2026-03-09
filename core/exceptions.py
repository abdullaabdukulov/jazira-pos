class POSError(Exception):
    pass


class APIConnectionError(POSError):
    pass


class APIResponseError(POSError):
    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(f"Server xatosi ({status_code}): {message}")


class ConfigurationError(POSError):
    pass


class SyncError(POSError):
    pass
