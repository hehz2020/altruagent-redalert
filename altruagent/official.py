from __future__ import annotations

import os
import re
import secrets
import threading

import httpx

from ._responses import _parse_error_body, _parse_json_body
from .client import AltruAgentClient
from .errors import MINT_FAILURE_PREFIX, AltruAgentError, AuthenticationError, ConfigurationError, PlatformError
from .models import OfficialAssignment, SeatGrant
from .notices import DASHBOARD_URL

OFFICIAL_AGENT_KEY_ENV = "ALTRUAGENT_OFFICIAL_AGENT_KEY"
AUTHENTICATE_PATH = "/tournament/agent/authenticate"
ASSIGNMENTS_PATH = "/tournament/agent/assignments"
_KEY_PATTERN = re.compile(r"^eak_live_[0-9a-f]{64}$")

_ERROR_MESSAGES = {
    "invalid_official_agent_key": (
        "The Official Agent Key was not accepted. Check that your agent is set to "
        "Self-hosted in Agent Configuration on the tournament dashboard, and that "
        "ALTRUAGENT_OFFICIAL_AGENT_KEY holds the key exactly as it was shown when you generated it. "
        "The dashboard can't show a key again: if you no longer have it, press Rotate key in "
        "Agent Configuration (or Generate Official Agent Key if you have no key), put the new key "
        "in ALTRUAGENT_OFFICIAL_AGENT_KEY, and restart."
    ),
    "registration_incomplete": (
        f"Your event registration isn't complete. Finish it on your dashboard ({DASHBOARD_URL})."
    ),
    "rate_limited": "Too many authentication attempts. Wait a minute and try again.",
    "agent_session_unavailable": (
        "The platform couldn't start an agent session just now. This is a temporary problem "
        "on the platform, not your key; try again in a minute."
    ),
    "assignment_not_found": "That tournament assignment was not found for this agent.",
    "assignment_not_grantable": "That assignment has already ended, or is being closed with no result.",
    "seat_busy": (
        "This seat is being played by another runtime using your Official Agent Key "
        "(or a previous run's hold on it hasn't expired yet)."
    ),
    "lease_not_held": "This runtime no longer holds the seat's lease.",
}


class OfficialAgentError(AuthenticationError):


    next_step: str | None = None


_RULES_MESSAGE = f"Accept the updated Official Rules on your dashboard ({DASHBOARD_URL})."


_MINT_FAILURE_PREFIX = MINT_FAILURE_PREFIX


def _is_mint_failure(code: str | None, detail: str | None) -> bool:
    return code == "invalid_official_agent_key" and (detail or "").startswith(_MINT_FAILURE_PREFIX)


def _error_from(response: httpx.Response, fallback: str) -> OfficialAgentError:
    parsed = _parse_error_body(response)
    code = parsed["error"]
    body = _parse_json_body(response)
    next_step = body.get("next_step") if isinstance(body, dict) else None
    if _is_mint_failure(code, parsed["detail"]):
        message = _ERROR_MESSAGES["agent_session_unavailable"]
    elif code == "registration_incomplete" and next_step == "rules":
        message = _RULES_MESSAGE
    else:
        message = _ERROR_MESSAGES.get(code) or f"{fallback} (HTTP {response.status_code}" + (f", {code})" if code else ")")
    error = OfficialAgentError(message, status_code=response.status_code, error_code=code, detail=parsed["detail"])
    error.next_step = next_step if isinstance(next_step, str) else None
    return error


def is_registration_incomplete(exc: BaseException) -> bool:

    return isinstance(exc, OfficialAgentError) and exc.error_code == "registration_incomplete"


def registration_wait_message(exc: BaseException) -> str:

    if getattr(exc, "next_step", None) == "rules":
        what = f"Accept the updated Official Rules on your dashboard ({DASHBOARD_URL})"
    else:
        what = f"Your event registration isn't complete. Finish it on your dashboard ({DASHBOARD_URL})"
    return f"{what}; I'll keep trying."


def is_fatal_auth_error(exc: BaseException) -> bool:

    if not isinstance(exc, OfficialAgentError):
        return False
    if exc.error_code == "registration_incomplete":
        return False
    if exc.error_code == "invalid_official_agent_key":
        return not _is_mint_failure(exc.error_code, exc.detail)
    return exc.error_code is None and exc.status_code == 401


def load_official_agent_key(key: str | None = None) -> str:

    key = (key if key is not None else os.environ.get(OFFICIAL_AGENT_KEY_ENV) or "").strip()
    if not key:
        raise ConfigurationError(
            f"{OFFICIAL_AGENT_KEY_ENV} is not set. Generate your Official Agent Key in Agent "
            "Configuration on the tournament dashboard and add it to your environment or .env."
        )
    if not _KEY_PATTERN.match(key):
        raise ConfigurationError(
            f"{OFFICIAL_AGENT_KEY_ENV} doesn't look like an Official Agent Key "
            "(expected eak_live_ followed by 64 hex characters)."
        )
    return key


class OfficialAgentAuth:


    def __init__(self, official_agent_key: str) -> None:
        self._key = official_agent_key

    def __repr__(self) -> str:
        return "OfficialAgentAuth(official_agent_key=<redacted>)"

    def login(self, http: httpx.Client, control_url: str) -> str:
        try:
            response = http.post(AUTHENTICATE_PATH, json={"official_agent_key": self._key})
        except httpx.RequestError as exc:
            raise PlatformError(f"Could not reach the control plane at {control_url}: {exc}", status_code=None) from exc
        if response.status_code != 200:
            raise _error_from(response, "Official agent authentication failed")
        body = _parse_json_body(response)
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise OfficialAgentError("The authentication response did not include a session token.",
                                     status_code=response.status_code)
        return token


class OfficialAgentClient:


    def __init__(
        self,
        control_url: str | None = None,
        official_agent_key: str | None = None,
        *,
        load_env_file: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if load_env_file:
            from dotenv import load_dotenv

            load_dotenv()
        key = load_official_agent_key(official_agent_key)
        self._client = AltruAgentClient(
            control_url, auth=OfficialAgentAuth(key), load_env_file=False, transport=transport
        )
        self.control_url = self._client.control_url
        self._lock = threading.RLock()

    def __enter__(self) -> "OfficialAgentClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def authenticate(self) -> None:

        with self._lock:
            self._client.login()

    def session_token(self) -> str | None:

        with self._lock:
            return self._client._access_token

    def use_session_token(self, token: str) -> None:

        with self._lock:
            self._client._access_token = token

    def assignments(self) -> list[OfficialAssignment]:

        with self._lock:
            data = self._client.request("GET", ASSIGNMENTS_PATH)
        rows = data.get("assignments") if isinstance(data, dict) else None
        return [OfficialAssignment.from_dict(row) for row in rows or [] if isinstance(row, dict)]

    def grant(self, seat_id: str, execution_id: str) -> SeatGrant:

        data = self._post(f"{ASSIGNMENTS_PATH}/{seat_id}/grant", execution_id)
        grant = SeatGrant.from_dict(data if isinstance(data, dict) else {})
        if not (grant.access_token and grant.game_session_id and grant.gameapi_server_url and grant.agent_id):
            raise OfficialAgentError("The seat grant response was missing required fields.")
        return grant

    def renew_lease(self, seat_id: str, execution_id: str) -> dict:

        data = self._post(f"{ASSIGNMENTS_PATH}/{seat_id}/lease/renew", execution_id)
        return data if isinstance(data, dict) else {}

    def _post(self, path: str, execution_id: str):
        try:
            with self._lock:
                return self._client.request("POST", path, json={"execution_id": execution_id})
        except PlatformError as exc:
            if exc.error_code in _ERROR_MESSAGES:
                raise OfficialAgentError(
                    _ERROR_MESSAGES[exc.error_code], status_code=exc.status_code,
                    error_code=exc.error_code, detail=exc.detail,
                ) from None
            raise


def new_execution_id() -> str:

    return secrets.token_urlsafe(32)


class OfficialSeatAuth:


    def __init__(self, official: OfficialAgentClient, seat_id: str, execution_id: str) -> None:
        self._official = official
        self.seat_id = seat_id
        self._execution_id = execution_id
        self._grant: SeatGrant | None = None

    def __repr__(self) -> str:
        return f"OfficialSeatAuth(seat_id={self.seat_id!r}, grant={self._grant!r})"

    @property
    def grant(self) -> SeatGrant | None:
        return self._grant

    def login(self, http: httpx.Client, control_url: str) -> str:
        grant = self._official.grant(self.seat_id, self._execution_id)
        if self._grant is not None and (grant.seat_id, grant.game_session_id) != (
            self._grant.seat_id, self._grant.game_session_id,
        ):
            raise OfficialAgentError("Seat renewal returned a different seat than the one assigned.")
        self._grant = grant
        return grant.access_token



LEASE_RENEW_SECONDS = 10.0
LEASE_RETRY_SECONDS = 5.0


class SeatLeaseLost(AltruAgentError):
    pass


class SeatLeaseKeeper:


    def __init__(
        self,
        official: "OfficialAgentClient",
        seat_id: str,
        execution_id: str,
        *,
        renew_seconds: float = LEASE_RENEW_SECONDS,
        retry_seconds: float = LEASE_RETRY_SECONDS,
        log=print,
    ) -> None:
        self._official = official
        self._seat_id = seat_id
        self._execution_id = execution_id
        self._renew_seconds = renew_seconds
        self._retry_seconds = retry_seconds
        self._log = log
        self._stop = threading.Event()
        self._failing = False
        self.lost = threading.Event()
        self.renewals = 0
        self._thread = threading.Thread(target=self._run, name=f"seat-lease-{seat_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        delay = self._renew_seconds
        while not self._stop.wait(delay):
            delay = self.renew_once()
            if delay is None:
                return

    def renew_once(self) -> float | None:

        try:
            self._official.renew_lease(self._seat_id, self._execution_id)
        except OfficialAgentError as exc:
            if exc.error_code == "lease_not_held":
                return self._reacquire()
            return self._handle(exc)
        except Exception as exc:
            return self._failed(exc)
        return self._renewed()

    def __repr__(self) -> str:
        return f"SeatLeaseKeeper(seat_id={self._seat_id!r})"

    def _reacquire(self) -> float | None:
        try:
            self._official.grant(self._seat_id, self._execution_id)
        except OfficialAgentError as exc:
            return self._handle(exc)
        except Exception as exc:
            return self._failed(exc)
        self._log("Seat lease re-acquired.")
        return self._renewed()

    def _handle(self, exc: OfficialAgentError) -> float | None:
        if exc.error_code == "seat_busy":
            self._log("Lost this seat to another runtime; stopping this match.")
            self.lost.set()
            return None
        if exc.error_code in ("assignment_not_grantable", "assignment_not_found"):
            return None
        return self._failed(exc)

    def _renewed(self) -> float:
        self.renewals += 1
        if self._failing:
            self._log("Seat lease renewal recovered.")
            self._failing = False
        return self._renew_seconds

    def _failed(self, exc: Exception) -> float:
        if not self._failing:
            self._log(f"Seat lease renewal failed ({exc}); retrying in {self._retry_seconds:.0f}s.")
            self._failing = True
        return self._retry_seconds
