Download **AltruAgentRedAlert-Windows-x64.zip**, extract it, and run **AltruAgentRedAlert.exe**. Python is included; no separate Python installation is needed.

**Policy v2.1:** retries missing game configuration, refreshes late map data, fixes the vehicle-budget selection gap, prevents aircraft from recalling ground-only defenders, and moves artillery into a verified firing position against visible structures. These corrections have regression coverage; competitive improvement is not yet measured.

Finish the current match before stopping the old launcher. Start the new EXE and check that its first line says **Bot v2.1**. Downloading an update does not replace an already running process.

Choose Testing, Tournament, both, or connection check. Enter your own Official Agent Key at the hidden prompt. The executable does not contain credentials and does not save the entered key to disk. An existing private `.env` beside the EXE is also supported.

Keep the program running and the computer awake and online. One running launcher supports multiple assigned seats. Register and configure Self Hosted on the platform separately.

This release was built on Windows x64 and the actual EXE passed an offline controller check and a spawned-worker check. `build-info.json` records its source commit and full dependency versions. `SHA256SUMS.txt` verifies download integrity. These checks establish packaging and runtime behavior, not competitive win rate.

The README in the ZIP includes Chinese setup instructions.
