# AltruAgent 红警程序 bot — v0.1

这是适配 AltruAgent 官方 Python starter 的可运行程序基线。红警分支完全不用 LLM，不产生模型调用费用。它不是移植的冠军 bot，也还没有在你的平台账号中打过测试局；离线测试只验证程序与接口行为，不能证明胜率。

## 安装到现有 self-hosted 项目

1. 解压本包，将 `altru_redalert/` 文件夹放在你的 starter 项目根目录，与 `agent/`、`altruagent/`、`examples/` 并列。将 `redalert_bot_tests/` 也放在那里即可运行随包测试。无需替换原来的 `agent/agent.py`。
2. 在该目录打开终端，使用你原来运行 starter 的 Python 3.11+ 环境。若还没有安装 starter 依赖，执行 `python -m pip install -e .`。
3. 沿用你的 `.env`：`ALTRUAGENT_CONTROL_URL=https://api.altruagent-game.com` 和你自己的 `ALTRUAGENT_OFFICIAL_AGENT_KEY`。本包不含凭证。
4. 先停止同一 agent key 下旧的运行进程，再启动本模块。不要同时运行旧版本和新版本争抢相同席位。

依次执行：

```bash
python -m unittest discover -s redalert_bot_tests -v
python -m agent --check-tournament --agent altru_redalert
python -m agent --match --agent altru_redalert
```

最后一个命令持续等待并加入你在平台 Testing 页面创建/加入的测试局。Testing 席位须选 Mine (self-hosted)。本包不会替你创建测试局或提交正式比赛版本。

完成测试并按主办方规定冻结提交后，正式比赛使用：

```bash
python -m agent --tournament --agent altru_redalert
```

`--match` 仅测试，不能代替 `--tournament`。比赛需要在 Dashboard 中注册相应 tournament，并让程序在整个比赛期间保持在线。

## 同时参加宝可梦或狼人杀

模块只重写红警决策。其他游戏默认延迟委托官方 `examples.llm_agent`，该分支仍需要你原来的模型配置和 `OPENAI_API_KEY`。运行纯红警测试不会初始化这个 LLM。

如果你已有其他游戏的自定义程序，在 `.env` 加：

```dotenv
REDALERT_OTHER_AGENT=agent.agent
```

这里必须是你真正实现了其他游戏的模块；官方原装 `agent.agent` 是占位符，并不是合格的宝可梦程序。也支持 `module_name:factory_name`。

`--check-tournament --agent altru_redalert` 只验证本模块能够创建及平台连接；不会提前验证延迟加载的其他游戏模型密钥。其他游戏仍应单独测试。

## 已实现的行为

- 近距离出生优先兵营，远距离优先矿场；这个阈值是待实战比较的策略参数。
- 展开基地车、放置已完成建筑、补电、关键建筑维修、恢复闲置矿车。
- 小规模前期步兵，保持短生产队列，预留关键建设与矿车恢复资金。
- 渐进增加矿场和矿车，配置允许且预算充足时升级维修厂及可用坦克。
- 按可见敌军调整车辆/火箭兵；防空建筑仅在当前配置提供成本、电力且允许生产时使用。
- 一个步兵侦察、主力集结推进、适量留守；局部劣势、空袭或重伤时撤退。
- 记忆本局合法看到的建筑位置，搜索地图，追击当前可见的敌方基地车。
- 结束前避免排入来不及完成的生产，依据己方已知战损减少冒险；不会把己方正净击杀当作已知领先。
- 对指令做归属、当前视野、边界与数量检查；追踪 pending 指令，处理最终拒绝/丢失反馈。

生产成本、电力、地图和可用单位优先读取 `context.game_config`。配置缺失时只使用官方公开指南中有明确数值的基础生产选项，不猜高级单位的价格。

## 记录测试局，便于调参

可选地在 `.env` 加：

```dotenv
REDALERT_LOG_DIR=redalert_logs
```

每场红警会生成一个本地 `.jsonl` 文件，包含经过字段筛选的本方观察、指令和反馈。它不记录登录请求、headers、token、席位授权或任意错误详情。默认不启用；日志仅用于离线分析，不会成为下一局的记忆。

摘要命令：

```bash
python -m altru_redalert.inspect_log redalert_logs/实际文件名.jsonl
```

建议先打双方阵营、三张地图上的测试局。记录官方最终胜负，并比较首矿场/首工厂时间、矿车损失、低电、无效订单与最终战损。日志里的最后一次观察不能代替官方胜负结果。不要只用一局胜利认定版本更强。

若要把代码放入公开参赛仓库，请将日志目录加入 `.gitignore`；日志留在本地用于复盘。`.env` 沿用官方 starter 的忽略规则。

## 已知范围与限制

- 尚未连接你的席位，未验证真实平台胜率、地图寻路、建筑摆放或网络耗时。
- 战斗判断使用成本/血量/距离近似，没有完整的射程、武器克制、弹道或伤害模拟。它是地面部队基线，没有空军/海军/超武的完整策略。
- 静态地图搜索只是近似可通行区域；单位拥堵、桥梁、动态地形和具体建筑占地仍由引擎处理。
- 不改变官方网络传输层；“本地决策很快”不等于服务器执行频率。实时反馈仍受网络与平台节流约束。
- 八秒内没有观察到生产/部署结果的在途意图会进入有界恢复。极端延迟下它不是严格 exactly-once；`unconfirmed_expiries` 出现时应查看测试局日志。
- 断线重启时，SDK 会恢复比赛；策略会由当前本方观察重建，而之前仅存在内存中的侦察记忆会丢失。
- 每局使用独立的新实例。不会读取直播、观战状态、对手私有日志或其他对局数据。

## 验证与来源

SDK 参考版本：`951f4f74b008c6aa7f40bec09e741aa67d3c45cc`，读取于 2026-10-13。

- Starter: https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter
- 红警接口: https://api.altruagent-game.com/skill/redalert
- 人类操作指南: https://platform.altruagent-game.com/tournament/agent-guide
- 规则: https://platform.altruagent-game.com/tournament/rules

公开截止日期当前存在冲突：报名页为 10 月 15 日 19:00 PDT，平台规则/指南仍为 10 月 13 日 23:59 PDT。以主办方明确确认的适用截止日期为准；不要在已锁定后自行更新正式参赛版本。

测试结果见 `VALIDATION.txt`。随包模拟经济测试故意使用合成收入及简化引擎，只检查队列、预算和响应延迟；不模拟对手，也不产生胜率数据。
