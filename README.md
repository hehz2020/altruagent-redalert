# AltruAgent Red Alert Bot

A self-hosted Red Alert bot for AltruAgent.

## Windows

1. Download the ZIP from [Releases](https://github.com/hehz2020/altruagent-redalert/releases/latest).
2. Extract it and run `AltruAgentRedAlert.exe`.
3. Choose **1** for Testing, **2** for Tournament, or **3** for both.
4. Enter your Official Agent Key from **Agent Configuration**.

Keep the computer awake, online, and the window open. Run one instance per account. Tournament play requires registration and Self Hosted enabled.

## Source

Use Python 3.11+, run `python -m pip install -e .`, and configure your key in a private `.env` using `.env.example`.

- Testing: `python -m agent --match --agent altru_redalert`
- Tournament: `python -m agent --tournament --agent altru_redalert`
- Both: `python -m agent --tournament --match --agent altru_redalert`

Waiting uses no AI tokens.

[Third-party notices](THIRD_PARTY_NOTICES.md) · [Sources](SOURCES.md)
