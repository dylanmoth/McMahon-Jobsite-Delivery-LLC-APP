class McMahonDispatchError(Exception):
    """Base exception for safe application errors."""


class AuthenticationError(McMahonDispatchError):
    pass


class AuthorizationError(McMahonDispatchError):
    pass


class ValidationError(McMahonDispatchError):
    pass
