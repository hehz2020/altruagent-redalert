from altruagent import DecisionContext, GameState, LegalAction, SendMessage, TERMINATE_MESSAGING


class WerewolfAgent:
    def __init__(self) -> None:
        self._spoke_on_day: int | None = None

    def choose_action(self, state: GameState, context: DecisionContext) -> LegalAction:
        return state.legal_actions[0]

    def choose_message(self, state: GameState, context: DecisionContext):
        for message in state.new_messages:
            print(f"[{context.session_id}] Player{message.sender} says: {message.content!r}")

        day = (state.raw.get("game_state") or {}).get("day")
        if self._spoke_on_day == day:
            return TERMINATE_MESSAGING

        self._spoke_on_day = day
        return SendMessage("I'm a villager. Let's hear from everyone before we vote.")


def create_agent():
    return WerewolfAgent()
