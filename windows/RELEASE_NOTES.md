# Red Alert bot v2.6

Download **AltruAgentRedAlert-Windows-x64.zip**, extract it, and run **AltruAgentRedAlert.exe**. No separate Python installation is needed.

This version addresses early infantry attacks and conflicting defense orders. It reserves four opening rifle infantry, briefly waits for cheap escort options when a new factory becomes ready, and reacts to visible infantry groups approaching key assets. Optional unfinished depot or extra-harvester production can be cancelled one item at a time; refunded money is not spent until it appears in a later observation.

Recalled defenders retain their assignments through brief gaps in contact. Local retreats have their own state and bounded destinations, and defense allocation takes place before scout selection.

The frozen runtime passed 1,107 tests and 24 subtests. The 24 valid paired conditions not used for further tuning produced 22 wins/2 losses for v2.6 and 21 wins/3 losses for v2.5: one additional win overall. Against Ryan's offline rule-based configuration, the 12 held-out conditions produced 11 wins/1 loss versus 10 wins/2 losses. The 12 regression conditions against six other bots produced 11 wins/1 loss for each version, including one improvement against Henry and one genuine game loss against Friendly. Six original development conditions, reported separately, produced 6 wins versus 5 wins/1 loss. These small samples do not establish a general win-rate improvement. See `VALIDATION_V26.md` for source hashes, early failed candidates and all invalid-attempt handling.

The bot reads the public map ID and static layout and already uses terrain-aware planning. This version does not add a named-map selector or claim an optimal strategy for each map. Historical engine results in `BENCHMARK.md` apply only to the versions named there.

Finish the current match, close the old launcher, then start this EXE. Its first line should say **Bot v2.6**. Choose **3** to accept both Testing and Tournament assignments. Enter your Official Agent Key at the hidden prompt.

The archive contains the Windows x64 executable, instructions, build identity, self-test results and checksums. No API key is bundled.
