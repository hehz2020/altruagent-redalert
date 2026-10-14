# AltruAgent Red Alert Bot — v2

A deterministic, self-hosted Red Alert bot for AltruAgent. The Red Alert strategy does not use an LLM or require a model API key. Its independent Python policy adopts ideas from [Spearhead AI](https://github.com/Vintorez91/Spearhead-AI): continuous production, protected economic recovery, resource-oriented expansion, reconnaissance memory and coordinated local combat. It is an adaptation to the platform player interface, not the original native-engine bot. See [sources and attribution](SOURCES.md).

## Windows: download and run

Use the delivered Windows ZIP, or a published build from [Releases](https://github.com/hehz2020/altruagent-redalert/releases/latest). Extract the whole archive and double-click **AltruAgentRedAlert.exe**. Python is included. For portable builds, keep the `runtime` and `app` directories beside the EXE.

1. Choose **1** for Testing, **2** for Tournament, or **3** for both.
2. Paste your Official Agent Key at the hidden prompt and press Enter.
3. Keep the window open and your computer awake and online. Stop the old bot first; use one launcher per account.

For Testing, select Red Alert and **Mine (self-hosted)** on the platform. Tournament participation still requires the platform's registration and Self Hosted configuration. This program does not register, submit or create matches.

Get your Official Agent Key from the platform's **Agent Configuration** page. The entered key stays in process memory. An existing private `.env` beside the EXE is also supported. Build metadata records the source, dependency versions and validation environment. A portable build made in Linux has static PE checks and Python logic tests; it is not evidence of an actual Windows runtime test. The native Windows CI release has the additional executable self-test gate described below.

[中文使用与策略说明](README_REDALERT_ZH.md) · [Validation record](VALIDATION.txt)

## What changed in v2

- Production batches sized to observed decision cadence, available funds and remaining time; reserves include unpaid queue tails and unconfirmed orders.
- Harvester recovery and retreat, power management, resource-directed refineries and conservative MCV expansion.
- Separate scouting, defense, main-force and harassment roles; visible-target focus fire, weapon/armor estimates, artillery spacing, local strength and stable retreat decisions.
- Historical sightings guide movement only. Attack target IDs must be currently visible; every order is checked against ownership, legal actions, map bounds and server limits.
- Persistent MCP sessions are enabled by the Windows launcher. Ambiguous action failures are not automatically replayed; the controller reconciles fresh observations. Per-phase timing separates network time from policy time.

These changes address issues seen in earlier platform traces. Offline checks do not establish a new competitive win rate or guarantee victory. Weapon fallbacks are estimates; actual runtime configuration takes precedence.

## Run from source

Use Python 3.11+. From the repository root:

```bash
python -m pip install -e .
```

Copy `.env.example` to your private `.env`, set `ALTRUAGENT_OFFICIAL_AGENT_KEY`, and set `ALTRUAGENT_PERSISTENT_MCP=1` to use connection reuse. Then:

```bash
python -m agent --check-tournament --agent altru_redalert
python -m agent --match --agent altru_redalert
```

For registered tournament games, stop the Testing process and use either command:

```bash
python -m agent --tournament --agent altru_redalert
python -m agent --tournament --match --agent altru_redalert
```

The second command accepts both tournament and Testing assignments. Waiting uses no AI tokens. The Red Alert policy itself uses no AI tokens either. Optional local diagnostics: `REDALERT_LOG_DIR=redalert_logs`.

## Development and scope

```bash
python -m pip install -e '.[dev]'
python -m pytest tests redalert_bot_tests windows/tests -q
```

[Windows build instructions](windows/README.txt) and the Actions workflow produce a real Windows x64 EXE and test a frozen spawned worker before publishing. The policy covers Red Alert ground warfare; it has no complete air/naval campaign. Other assigned games delegate to `REDALERT_OTHER_AGENT`, defaulting to `examples.llm_agent`, which needs separate model configuration.

This repository includes the [official starter](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter); its original documentation is [README_STARTER.md](README_STARTER.md). No credentials or recorded matches are bundled.
