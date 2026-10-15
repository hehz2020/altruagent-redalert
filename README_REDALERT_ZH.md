# AltruAgent 红警 bot v2.1

这是基于 Spearhead AI 的公开思想、针对平台接口独立实现的传统程序 bot。红警决策不用 LLM，也不需要 OpenAI API Key。它不是把原版 Spearhead 的引擎插件直接装进平台，而是使用平台允许的观察和指令重新实现经济、侦察和作战逻辑。来源见 [SOURCES.md](SOURCES.md)。

## Windows 使用

1. 使用交付的 Windows ZIP；发布后也可从 [Releases](https://github.com/hehz2020/altruagent-redalert/releases/latest) 下载。将整个包解压到一个文件夹，便携版的 `runtime`、`app` 文件夹必须留在 EXE 旁边。
2. 等当前对局结束后关闭旧 bot，再双击 `AltruAgentRedAlert.exe`，不需要安装 Python。新窗口首行应显示 **Bot v2.1**；下载文件不会自动替换已经运行的旧程序。
3. 输入 `1` 接测试局；输入 `2` 接正式比赛；输入 `3` 同时接两类。输入 `4` 只检查连接。
4. 粘贴自己的 Official Agent Key，回车。隐藏输入时看不到字符是正常现象。
5. 保持窗口打开、电脑联网并且不休眠。同一账号只启动一个程序。

测试对局需在平台选择 Red Alert，对应席位选择 **Mine (self-hosted)**。正式比赛还需在平台完成报名和 Self Hosted 设置。程序不会自动报名、提交版本或创建比赛。平台显示等待玩家时，要确认双方席位都已连接，程序在线并不代表对手也已连接。

Key 不在程序包中，现场输入的 Key 不写入磁盘。已有私密 `.env` 可以放在 EXE 旁，格式为 `ALTRUAGENT_OFFICIAL_AGENT_KEY=你的Key`。不要公开这个文件。按 Ctrl+C 停止程序。

## 这一版的改动

v2.1 修复了几处已复现的问题：

- 开局读取游戏配置失败后，按 5–30 秒退避重试；恢复后更新地图规划，避免整局缺少高级兵种价格和地图数据。
- 统一选车和实际生产使用的预留金额，避免“选中较贵坦克后放弃下单，较便宜车辆也不造”的资金死区。
- 空中袭扰只抽调能够攻击飞机的守军，不再把不能对空的坦克全拉回家。
- 炮兵独立选择对可见建筑的射击位置，避免跟随前排后退、永久停在射程以外。
- 启动窗口和本地对局日志标明策略版本；日志注明是否读到游戏配置。

这些是运行与战斗逻辑修复，尚不代表已测得平台胜率。以下为 v2 系列的整体能力：

- **减少生产空转**：根据观察间隔、资金和剩余时间，一次安排多名步兵或适量车辆。计算整条队列尚未支付的费用，为关键建筑、矿车恢复和扩张预留资金。
- **扩张与经济恢复**：依据公开地图矿区和粗略陆路连通性选扩张点，移动基地车，避开已经看到的威胁；矿车遇险撤离、闲置后恢复采矿。
- **分队作战**：侦察、基地防守、主力和骚扰分工；根据局部敌我强弱决定推进或撤退，使用可见目标集火，并让炮兵保持后方支援距离。
- **更细的战斗估计**：结合单位血量、射程、速度和公开武器/装甲数值估算有效火力。它不是完整的引擎伤害模拟。
- **合法视野记忆**：记住本局看见过的敌人位置，过期后清除。旧位置可以作为侦察方向，隐藏敌人的 ID 不能用于直接攻击。
- **运行修复**：已完成车辆不再误当建筑放置；批量生产只释放已经观察到的部分预算；遵守平台指令数量限制。Windows 默认复用 MCP 连接，并记录读取、决策、发送等阶段耗时。

旧日志中曾出现有钱却单个造兵、队列频繁空着，以及把已完成坦克当建筑放置的问题。这一版针对这些问题增加了回归检查。旧对局记录的离线回放只能检查指令与计算行为，不能证明新版已经赢过对手。

## 源码运行

安装 Python 3.11+，在仓库根目录执行：

```bash
python -m pip install -e .
```

设置私密 `.env`：

```dotenv
ALTRUAGENT_CONTROL_URL=https://api.altruagent-game.com
ALTRUAGENT_OFFICIAL_AGENT_KEY=在这里填写自己的Key
ALTRUAGENT_PERSISTENT_MCP=1
REDALERT_LOG_DIR=redalert_logs
```

检查后开始接测试局：

```bash
python -m agent --check-tournament --agent altru_redalert
python -m agent --match --agent altru_redalert
```

正式比赛改用 `--tournament`，也可以同时使用 `--tournament --match`。停止旧进程后再切换。

若需回退连接复用，将 `ALTRUAGENT_PERSISTENT_MCP=0`。传输异常后的下一个请求会重新连接；结果不明的下单不会由传输层自动重发。策略仍需用后续观察确认是否已执行，不是严格的 exactly-once 保证。

## 日志与验证

EXE 默认将脱敏对局日志保存在 `%LOCALAPPDATA%\AltruAgentRedAlert\logs`。源码版通过 `REDALERT_LOG_DIR` 启用。日志包含本方观察、订单、反馈及数值耗时，不包含登录请求、凭证或任意异常详情；不会用作下一局的侦察记忆。

```bash
python -m altru_redalert.inspect_log redalert_logs/实际文件名.jsonl
python -m pytest tests redalert_bot_tests windows/tests -q
```

[VALIDATION.txt](VALIDATION.txt) 记录离线验证范围。GitHub CI 发布流程会在 Windows 上构建 EXE 并测试其工作子进程；本地交叉编译的便携版仅经过 PE 格式和 Python 逻辑检查，不等于 Windows 实机验证。请以包内构建记录为准。

## 使用范围

- 只通过当前席位的合法观察和公开配置决策，不读取观战、直播或对手私有数据。
- 宏观地图采用公开静态地形；矿石消耗、单位拥堵、动态障碍和建筑落点仍取决于引擎实际状态。
- 武器参数缺失时，使用 OpenRA release-20250330 的公开数值估计。平台的实际引擎提交不完全等同于该版本，估计并非精确战斗模拟。
- 地面战、炮兵和防空是主要范围，没有完整海军/空军/超武战役策略。
- 批量订单确认采用有界超时恢复。极端延迟、暂停生产等情况下仍需检查日志中的 `unconfirmed_expiries`。
- 断线恢复会重建当前局面；进程重启会丢失此前只存在内存中的侦察信息。
- 其他游戏仍交给 `REDALERT_OTHER_AGENT`，默认 `examples.llm_agent`，需要另行配置并测试。

优化目标是提高平台实战表现。没有任何一套离线测试能保证必胜；新版对不同对手的真实胜率仍需平台对局验证。
