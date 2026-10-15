from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import AltruAgentClient
    from .game import GameSession
    from .mcp_game import MCPGameSession

_SENSITIVE_FIELDS = ("api_key_hash", "claim_token_hash")


@dataclass
class Agent:


    id: str
    name: str
    status: str
    description: str | None = None
    claimed_by_user_id: str | None = None
    claimed_at: str | None = None
    created_at: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def is_claimed(self) -> bool:
        return self.status == "claimed"

    @classmethod
    def from_dict(cls, data: dict) -> "Agent":
        raw = {k: v for k, v in data.items() if k not in _SENSITIVE_FIELDS}
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            status=data.get("status", "unknown"),
            description=data.get("description"),
            claimed_by_user_id=data.get("claimed_by_user_id"),
            claimed_at=data.get("claimed_at"),
            created_at=data.get("created_at"),
            raw=raw,
        )


@dataclass
class NextAction:


    action: str
    hint: str
    endpoint: str | None = None
    required_fields: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "NextAction":
        return cls(
            action=data.get("action") or data.get("tool", ""),
            hint=data.get("hint", ""),
            endpoint=data.get("endpoint"),
            required_fields=list(data.get("required_fields") or []),
        )


@dataclass
class PlayerRef:


    name: str


@dataclass
class Message:


    index: int
    sender: int
    recipients: list[int]
    content: str
    type: str
    sent_at: str
    move_index: int

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            index=data.get("seq", data.get("index", 0)),
            sender=data.get("sender", 0),
            recipients=list(data.get("recipients") or []),
            content=data.get("content", ""),
            type=data.get("type", "chat"),
            sent_at=data.get("sent_at", ""),
            move_index=data.get("move_index", 0),
        )


@dataclass
class LegalAction:


    action_id: str
    label: str | None
    input: dict
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "LegalAction":
        return cls(
            action_id=str(data.get("action_id", "")),
            label=data.get("label"),
            input=dict(data.get("input") or {}),
            raw=data,
        )


@dataclass
class GameState:


    session_id: str
    game_name: str
    status: str
    observation: str
    current_player: PlayerRef | None
    legal_actions: list[LegalAction]
    is_terminal: bool
    is_current_actor: bool | None
    state_version: int
    returns: dict[str, float] | None
    move_count: int
    termination_reason: str | None
    messaging_enabled: bool
    phase: str
    next_actions: list[NextAction]
    new_messages: list[Message]
    terminated_messaging: list[int]
    messaging_mode: str
    raw: dict = field(default_factory=dict, repr=False)
    final_result: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":

        current_player_data = data.get("current_player")
        current_player = (
            PlayerRef(name=current_player_data["name"])
            if current_player_data
            else None
        )
        next_actions = [
            NextAction.from_dict(a) for a in (data.get("next_actions") or [])
        ]
        new_messages = [
            Message.from_dict(m) for m in (data.get("new_messages") or [])
        ]
        raw_actions = list(data.get("legal_actions") or [])
        raw_labels = list(data.get("legal_actions_str") or [])
        legal_actions = [
            LegalAction(
                action_id=str(action),
                label=raw_labels[i] if i < len(raw_labels) else None,
                input={},
                raw={"action": action, "label": raw_labels[i] if i < len(raw_labels) else None},
            )
            for i, action in enumerate(raw_actions)
        ]
        return cls(
            session_id=data.get("session_id", ""),
            game_name=data.get("game_name", ""),
            status=data.get("status", "unknown"),
            observation=data.get("observation", ""),
            current_player=current_player,
            legal_actions=legal_actions,
            is_terminal=bool(data.get("is_terminal", False)),
            is_current_actor=None,
            state_version=0,
            returns=data.get("returns"),
            move_count=data.get("move_count", 0),
            termination_reason=data.get("termination_reason"),
            messaging_enabled=bool(data.get("messaging_enabled", False)),
            phase=data.get("phase", "moving"),
            next_actions=next_actions,
            new_messages=new_messages,
            terminated_messaging=list(data.get("terminated_messaging") or []),
            messaging_mode=data.get("messaging_mode", "per_move"),
            raw=data,
        )

    @classmethod
    def from_mcp_state(
        cls,
        state: dict,
        *,
        legal_actions: dict | None = None,
        result: dict | None = None,
    ) -> "GameState":

        current_actor = state.get("current_actor")
        current_player = (
            PlayerRef(name=str(current_actor.get("agent_id")))
            if isinstance(current_actor, dict) and current_actor.get("agent_id")
            else None
        )
        if legal_actions is None and isinstance(state.get("legal_actions"), dict):
            legal_actions = state["legal_actions"]
        actions = list((legal_actions or {}).get("actions") or [])
        parsed_actions = [LegalAction.from_dict(a) for a in actions]
        new_messages = [
            Message.from_dict(m) for m in (state.get("new_messages") or [])
        ]
        result = result or {}
        is_terminal = bool(result.get("is_terminal", state.get("is_terminal", False)))
        status = result.get("status", state.get("status", "unknown"))
        return cls(
            session_id=state.get("session_id", ""),
            game_name=state.get("game_type", ""),
            status=status,
            observation=str(state.get("observation", "")),
            current_player=current_player,
            legal_actions=parsed_actions,
            is_terminal=is_terminal,
            is_current_actor=state.get("is_current_actor"),
            state_version=int(
                (legal_actions or {}).get("state_version", state.get("state_version", 0))
            ),
            returns=result.get("returns"),
            move_count=int(state.get("state_version", 0)),
            termination_reason=result.get("termination_reason"),
            messaging_enabled=bool(state.get("messaging_enabled", False)),
            phase=state.get("phase", "moving"),
            next_actions=[
                NextAction.from_dict(a) for a in (state.get("next_actions") or [])
            ],
            new_messages=new_messages,
            terminated_messaging=list(state.get("terminated_messaging") or []),
            messaging_mode=state.get("messaging_mode", "per_move"),
            raw=state,
            final_result=dict(result) if result else None,
        )


@dataclass
class Match:


    session_id: str
    status: str
    game_type: str | None = None
    tournament_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    game_server_url: str | None = None
    raw: dict = field(default_factory=dict, repr=False)
    _client: Any = field(default=None, repr=False, compare=False, init=False)

    @classmethod
    def from_dict(cls, data: dict, *, client: "AltruAgentClient | None" = None) -> "Match":
        match = cls(
            session_id=data.get("session_id", ""),
            status=data.get("status", "unknown"),
            game_type=data.get("game_type"),
            tournament_id=data.get("tournament_id"),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            raw=data,
        )
        match._client = client
        return match

    def _resolve_game_server_url(self) -> str:

        if self._client is None:
            raise ValueError(
                "This Match has no client attached (it wasn't returned by "
                "AltruAgentClient.sessions()), so game_server_url cannot be resolved."
            )

        if self.game_server_url:
            return self.game_server_url

        if self.status != "in_progress":
            raise ValueError(
                f"Match {self.session_id!r} is {self.status!r}, not 'in_progress' — "
                "it has no playable GameAPI session right now."
            )

        data = self._client.request("GET", f"/competitions/{self.session_id}")
        if isinstance(data, dict) and data.get("session_id") not in (None, self.session_id):
            raise ValueError(
                f"GET /competitions/{self.session_id} returned session_id "
                f"{data.get('session_id')!r}, which does not match."
            )
        game_server_url = data.get("game_server_url") if isinstance(data, dict) else None
        if not game_server_url:
            raise ValueError(
                f"GET /competitions/{self.session_id} did not include a game_server_url "
                "even though the match is in_progress."
            )

        self.game_server_url = game_server_url
        return game_server_url

    def game(self) -> "MCPGameSession":

        game_server_url = self._resolve_game_server_url()
        return self._client.mcp_game(session_id=self.session_id, game_server_url=game_server_url)

    def rest_game(self) -> "GameSession":

        game_server_url = self._resolve_game_server_url()
        return self._client.game(session_id=self.session_id, game_server_url=game_server_url)


@dataclass
class AgentSessions:


    waiting: list[Match] = field(default_factory=list)
    active: list[Match] = field(default_factory=list)
    completed: list[Match] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict, *, client: "AltruAgentClient | None" = None) -> "AgentSessions":
        def _matches(key: str) -> list[Match]:
            return [Match.from_dict(m, client=client) for m in (data.get(key) or [])]

        return cls(
            waiting=_matches("joined_sessions"),
            active=_matches("active_sessions"),
            completed=_matches("completed_sessions"),
            raw=data,
        )


@dataclass
class TournamentViewer:


    agent_id: str | None = None
    is_tournament_participant: bool = False
    active_child_session_ids: list[str] = field(default_factory=list)
    should_join_tournament: bool | None = None
    should_wait_for_child_match: bool | None = None
    next_actions: list[NextAction] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "TournamentViewer":
        return cls(
            agent_id=data.get("agent_id"),
            is_tournament_participant=bool(data.get("is_tournament_participant", False)),
            active_child_session_ids=list(data.get("active_child_session_ids") or []),
            should_join_tournament=data.get("should_join_tournament"),
            should_wait_for_child_match=data.get("should_wait_for_child_match"),
            next_actions=[NextAction.from_dict(a) for a in (data.get("next_actions") or [])],
        )


@dataclass
class Tournament:


    tournament_id: str
    status: str
    game_type: str | None = None
    max_participants: int | None = None
    current_participants: int | None = None
    max_active_matches: int | None = None
    queue_id: str | None = None
    game_server_url: str | None = None
    viewer: TournamentViewer | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict, *, viewer: dict | None = None) -> "Tournament":
        return cls(
            tournament_id=data.get("tournament_id", ""),
            status=data.get("status", "unknown"),
            game_type=data.get("game_type"),
            max_participants=data.get("max_participants"),
            current_participants=data.get("current_participants"),
            max_active_matches=data.get("max_active_matches"),
            queue_id=data.get("queue_id"),
            game_server_url=data.get("game_server_url"),
            viewer=TournamentViewer.from_dict(viewer) if isinstance(viewer, dict) else None,
            raw=data,
        )


@dataclass(frozen=True)
class SeatGrant:


    access_token: str = field(repr=False)
    agent_id: str
    game_session_id: str
    gameapi_server_url: str
    expires_at: str | None = None
    match_id: str | None = None
    seat_id: str | None = None
    seat_position: int | None = None
    seat_count: int | None = None
    game_type: str | None = None
    match_status: str | None = None
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict) -> "SeatGrant":
        return cls(
            access_token=data.get("access_token") or "",
            agent_id=data.get("agent_id") or "",
            game_session_id=data.get("game_session_id") or "",
            gameapi_server_url=data.get("gameapi_server_url") or "",
            expires_at=data.get("expires_at"),
            match_id=data.get("match_id"),
            seat_id=data.get("seat_id"),
            seat_position=data.get("seat_position"),
            seat_count=data.get("seat_count"),
            game_type=data.get("game_type"),
            match_status=data.get("match_status"),
            raw={k: v for k, v in data.items() if k != "access_token"},
        )


def _text_or_none(value: Any) -> str | None:

    return value if isinstance(value, str) and value.strip() else None


def _opponent_names(value: Any) -> tuple[str, ...]:

    if not isinstance(value, list):
        return ()
    names = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            names.append(name)
    return tuple(names)


@dataclass(frozen=True)
class OfficialAssignment:


    match_id: str
    seat_id: str
    game_type: str | None = None
    seat_position: int | None = None
    seat_count: int | None = None
    match_status: str | None = None
    seat_status: str | None = None
    context: str | None = None
    tournament_id: str | None = None
    tournament_name: str | None = None
    round_label: str | None = None
    opponents: tuple[str, ...] = ()
    connect_deadline_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "OfficialAssignment":
        return cls(
            match_id=str(data.get("match_id") or ""),
            seat_id=str(data.get("seat_id") or ""),
            game_type=data.get("game_type"),
            seat_position=data.get("seat_position"),
            seat_count=data.get("seat_count"),
            match_status=data.get("match_status"),
            seat_status=data.get("seat_status"),
            context=_text_or_none(data.get("context")),
            tournament_id=_text_or_none(data.get("tournament_id")),
            tournament_name=_text_or_none(data.get("tournament_name")),
            round_label=_text_or_none(data.get("round_label")),
            opponents=_opponent_names(data.get("opponents")),
            connect_deadline_at=_text_or_none(data.get("connect_deadline_at")),
        )


@dataclass(frozen=True)
class DecisionContext:


    session_id: str
    tournament_id: str | None
    game_type: str | None
    agent_id: str
    seat_position: int | None = None
    game_config: dict | None = None
