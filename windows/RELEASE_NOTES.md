Download **AltruAgentRedAlert-Windows-x64.zip**, extract it, and run **AltruAgentRedAlert.exe**. Python is included; no separate Python installation is needed.

**Policy v2.3:** a two-refinery opening, earlier sustained tank production, infantry/vehicle support recovery after the first tank core, connected-terrain group advances and whole-squad cancellation of unfavorable assaults. It retains visible-target focus fire, limited vehicle kiting, protected artillery and emergency economic recovery. See [BENCHMARK.md](https://github.com/hehz2020/altruagent-redalert/blob/main/BENCHMARK.md) for all candidate outcomes and a separate paired validation set. These local results are not platform tournament results or proof of a strongest bot.

Finish the current match before stopping the old launcher. Start the new EXE and check that its first line says **Bot v2.3**. Downloading an update does not replace an already running process.

Separate local validation: v2.3 **11 wins / 5 losses**, v2.2 **9 wins / 7 losses**, over the same 16 new conditions. Three v2.3 wins and two v2.2 wins were local time-limit score decisions. Paired outcomes: five improved, three regressed, eight unchanged. This small comparison does not establish a future win probability.

Choose Testing, Tournament, both, or connection check. Enter your own Official Agent Key at the hidden prompt. The executable does not contain credentials and does not save the entered key to disk. An existing private `.env` beside the EXE is also supported.

Keep the program running and the computer awake and online. One running launcher supports multiple assigned seats. Register and configure Self Hosted on the platform separately.

This release was built on Windows x64 and the actual EXE passed an offline controller check and a spawned-worker check. `build-info.json` records its source commit and full dependency versions. `SHA256SUMS.txt` verifies download integrity. These checks establish packaging and runtime behavior, not competitive win rate.

The README in the ZIP includes Chinese setup instructions.
