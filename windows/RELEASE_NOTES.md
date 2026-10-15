Download **AltruAgentRedAlert-Windows-x64.zip**, extract it, and run **AltruAgentRedAlert.exe**. Python is included; no separate Python installation is needed.

**Policy v2.2:** protects income/technology investment and a three-tank core, completes committed retreats even when pursuers disappear into fog, prevents depleted squads from renewing attacks indefinitely, and keeps emergency harvester savings from leaking into infantry production. It retains the configuration, vehicle-budget and artillery fixes from v2.1. See [BENCHMARK.md](https://github.com/hehz2020/altruagent-redalert/blob/main/BENCHMARK.md) for local engine comparisons, including losses and separate evaluation maps. These are not platform tournament results or proof of a strongest bot.

Finish the current match before stopping the old launcher. Start the new EXE and check that its first line says **Bot v2.2**. Downloading an update does not replace an already running process.

Choose Testing, Tournament, both, or connection check. Enter your own Official Agent Key at the hidden prompt. The executable does not contain credentials and does not save the entered key to disk. An existing private `.env` beside the EXE is also supported.

Keep the program running and the computer awake and online. One running launcher supports multiple assigned seats. Register and configure Self Hosted on the platform separately.

This release was built on Windows x64 and the actual EXE passed an offline controller check and a spawned-worker check. `build-info.json` records its source commit and full dependency versions. `SHA256SUMS.txt` verifies download integrity. These checks establish packaging and runtime behavior, not competitive win rate.

The README in the ZIP includes Chinese setup instructions.
