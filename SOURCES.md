# Sources and design attribution

## Platform integration

- Official starter: https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter
- Starter baseline inspected: `951f4f74b008c6aa7f40bec09e741aa67d3c45cc`.
- Player API: https://api.altruagent-game.com/skill/redalert
- Runtime public `game_config` and authorized seat observations provide actual legal actions, costs, units, maps and timings. Observed engine commit: `9b271c1a5562a07deeb1c3f81d9a556cd563a676`.

## Spearhead AI inspiration

- Author: Vintorez91 and project contributors.
- Source: https://github.com/Vintorez91/Spearhead-AI
- Reference release: https://github.com/Vintorez91/Spearhead-AI/releases/tag/v0.4.0-preview
- Reference archive SHA256: `98fec6165e79e19f1e564f346b789937fec0629054cee326baa8120f177d238d`.
- Upstream license: GNU GPL v3; consult the upstream archive for its terms.

The v2 Python policy was independently implemented after studying general ideas: protected economic recovery, resource-oriented MCV expansion, timestamped reconnaissance, local force evaluation, separate defense/attack/scout tasks, preservation and target selection. No Spearhead C# files, compiled plugin or assets are included. This is not an official Spearhead release, mechanical port or claim of identical behaviour. Spearhead's historical native-engine tests do not establish this bot's performance on AltruAgent.

## Weapon estimates

Numeric fallback weapon/armor facts were consulted from OpenRA `release-20250330`:

- https://github.com/OpenRA/OpenRA/tree/release-20250330/mods/ra/weapons
- `ballistics.yaml`, `smallcaliber.yaml`, `missiles.yaml`, `other.yaml`
- https://github.com/OpenRA/OpenRA/tree/release-20250330/mods/ra/rules
- `vehicles.yaml`, `infantry.yaml`, `structures.yaml`

`tactics.py` uses compact heuristic estimates rather than the engine's damage calculation. Runtime fields override available values. Missing reload, accuracy, armor and multi-weapon details make these estimates imperfect; the platform's observed engine is a different commit. No upstream engine code or game assets are bundled.
