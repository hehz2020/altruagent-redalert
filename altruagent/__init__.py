from .auth import ApiKeyAuth, SeatClaimError, SeatGrantAuth
from .client import AltruAgentClient
from .errors import AltruAgentError, AuthenticationError, ConfigurationError, PlatformError
from .game import GameSession
from .mcp_game import MCPGameSession
from .mcp_transport import MCPToolError
from .official import OfficialAgentAuth, OfficialAgentClient, OfficialAgentError, OfficialSeatAuth
from .models import (
    Agent,
    AgentSessions,
    DecisionContext,
    GameState,
    LegalAction,
    Match,
    Message,
    NextAction,
    OfficialAssignment,
    PlayerRef,
    SeatGrant,
    Tournament,
    TournamentViewer,
)
from .runner import (
    RESIGN,
    TERMINATE_MESSAGING,
    WAIT,
    DecisionError,
    RunnerError,
    SendMessage,
    UnsupportedGameFlowError,
    WithReasoning,
    run_game,
    run_match,
)
from .runtime import run_forever, run_once
from .supervisor import run_forever_concurrent, run_once_concurrent, run_tournament_forever

__all__ = [
    "AltruAgentClient",
    "ApiKeyAuth",
    "SeatGrantAuth",
    "SeatGrant",
    "SeatClaimError",
    "OfficialAgentAuth",
    "OfficialAgentClient",
    "OfficialAgentError",
    "OfficialAssignment",
    "OfficialSeatAuth",
    "Agent",
    "AgentSessions",
    "DecisionContext",
    "GameSession",
    "GameState",
    "LegalAction",
    "Match",
    "MCPGameSession",
    "MCPToolError",
    "Message",
    "NextAction",
    "PlayerRef",
    "Tournament",
    "TournamentViewer",
    "AltruAgentError",
    "ConfigurationError",
    "AuthenticationError",
    "PlatformError",
    "RESIGN",
    "TERMINATE_MESSAGING",
    "WAIT",
    "RunnerError",
    "DecisionError",
    "SendMessage",
    "UnsupportedGameFlowError",
    "WithReasoning",
    "run_game",
    "run_match",
    "run_forever",
    "run_once",
    "run_forever_concurrent",
    "run_once_concurrent",
    "run_tournament_forever",
]
