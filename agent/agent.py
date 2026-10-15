from altruagent import DecisionContext, GameState, LegalAction


def choose_action(state: GameState, context: DecisionContext) -> LegalAction:
    return state.legal_actions[0]


def create_agent():
    return choose_action
