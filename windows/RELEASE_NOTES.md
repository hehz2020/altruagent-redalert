Download **AltruAgentRedAlert-Windows-x64.zip**, extract it, and run **AltruAgentRedAlert.exe**. No separate Python installation is needed.

**Policy v2.5** improves threat-responsive production, siege support, concurrent defenses, target selection, map-search continuity and failed-order recovery. See [VALIDATION_V25.md](https://github.com/hehz2020/altruagent-redalert/blob/main/VALIDATION_V25.md) for validation and its limits. Earlier v2.3 match results are historical and do not establish v2.5 win rates.

Finish the current match, close the old launcher, then start this EXE. Its first line should say **Bot v2.5**. Choose **3** to accept both Testing and Tournament assignments. Enter your Official Agent Key at the hidden prompt.

Keep one launcher running per account, with the computer awake and online. Tournament registration and Self Hosted configuration are still required on the platform.

The Windows build checks the actual EXE and a spawned worker offline. `build-info.json`, `self-test.json` and `SHA256SUMS.txt` identify and validate this build. Credentials are not included.
