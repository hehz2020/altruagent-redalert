# AltruAgent Red Alert Bot

A self-hosted, deterministic Python bot for the AltruAgent OpenRA Red Alert tournament. The Red Alert strategy runs without an LLM or an OpenAI API key. It manages construction, harvesting, scouting, army grouping, defense, attack and retreat through the authorized player-facing SDK.

This repository includes the official [AltruAgent starter](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter), plus the `altru_redalert` package. See [the original starter README](README_STARTER.md) for SDK documentation and [the Chinese bot guide](README_REDALERT_ZH.md) for strategy, logging and configuration details.

## Setup on Windows

Use Python 3.11 or newer; the offline validation used Python 3.12. Open Command Prompt in this repository's root folder and run each line separately:

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
if not exist .env copy .env.example .env
notepad .env
```

In `.env`, replace `eak_live_your_key_here` with your Official Agent Key from the tournament dashboard. Keep `.env` private. Optional local observation logging can be enabled with `REDALERT_LOG_DIR=redalert_logs`.

Check the setup, then wait for Red Alert Testing matches:

```bat
.venv\Scripts\python.exe -m agent --check-tournament --agent altru_redalert
.venv\Scripts\python.exe -m agent --match --agent altru_redalert
```

On the platform's Testing page, select Red Alert and choose **Mine (self-hosted)** for your seat. Keep the process running, the computer connected and sleep disabled while playing. To stop it, press Ctrl+C.

For registered tournament games, stop the Testing process and run:

```bat
.venv\Scripts\python.exe -m agent --tournament --agent altru_redalert
```

Run only one dispatcher process for the account. This repository's creation does not register the agent, submit a version or start a live match. Follow the tournament's current submission and registration requirements.

## Other games

The custom strategy covers Red Alert. Other assigned games delegate to `REDALERT_OTHER_AGENT`, defaulting to `examples.llm_agent`; that fallback needs separate model/API configuration. A successful Red Alert setup check does not validate the fallback's credentials.

## Verification

The bot has passed 36 offline tests and a simulated integration check against the official SDK loop. These are not real game results; no live win rate has been measured. See [VALIDATION.txt](VALIDATION.txt).

```bat
.venv\Scripts\python.exe -m unittest discover -s redalert_bot_tests -v
```

Bot decisions use authorized observations and public configuration. Match-specific tactical memory starts fresh for each game. Dependencies are declared in `pyproject.toml`; no model weights, secrets or recorded match data are bundled.
