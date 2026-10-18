class VisionError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status

    def as_dict(self) -> dict:
        return {'ok': False, 'error': {'code': self.code, 'message': str(self)}}
