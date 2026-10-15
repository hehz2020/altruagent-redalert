from __future__ import annotations


class AltruAgentError(Exception):
    pass


class ConfigurationError(AltruAgentError):
    pass


class AuthenticationError(AltruAgentError):


    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


class PlatformError(AltruAgentError):


    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        error_code: str | None = None,
        detail: str | None = None,
        next_action: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.next_action = next_action


MINT_FAILURE_PREFIX = "Failed to mint agent session"

_TRANSIENT_ERROR_CODES = frozenset(
    {
        "RUNTIME_TEMPORARILY_UNAVAILABLE",
        "rate_limited",
        "agent_session_unavailable",
    }
)


def is_transient_error(exc: BaseException) -> bool:

    if not isinstance(exc, (PlatformError, AuthenticationError)):
        return False
    if getattr(exc, "protocol_error", False) or getattr(exc, "local_error", False):
        return False
    code, status = exc.error_code, exc.status_code
    if code in _TRANSIENT_ERROR_CODES:
        return True
    if code == "invalid_official_agent_key":
        return (exc.detail or "").startswith(MINT_FAILURE_PREFIX)
    if status is not None and (status >= 500 or status in (408, 429)):
        return True
    if type(exc) is AuthenticationError and status == 401:
        return True
    if code is not None:
        return False
    return status is None and isinstance(exc, PlatformError)
