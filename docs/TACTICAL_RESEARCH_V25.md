# v2.5 私有战术研究记录

记录日期：2026-10-16（UTC）。用途：帮助改进我方红警 1 / OpenRA bot，形成可复验的场景，不据此宣称击败任何对手。

本次研究只读取公开 GitHub 代码、配置和文档；没有联系作者，没有留言、提 issue/PR 或参加对局。仓库与 AltruAgent 有关，不等于已确认进入正式赛场，也不能证明公开 HEAD 就是参赛版本。固定提交用于复核，后续修改需另审。本记录归纳行为，不复制对手实现；公开可阅读与代码可再分发是不同问题。

**证据范围：**“代码事实”是所列提交的条件和调用路径；“应对”是我方可独立实现的策略建议；“待验证”表示尚未建立实战效果。没有完成这些完整对手与我方 v2.5 的真实引擎配对测试，也没有对手真实胜率。作者自报战绩、合成观察测试和我方旧版本基准不能替代此结果。

所有实战决策只使用当前席位合法可见的信息、本局曾见信息及公开静态地形。仓库代码用于赛前研究；运行时不需要识别作者身份，也不读取对手私有状态。

## 最值得优先处理的问题

1. 矿车承受连续小伤害时，应按时间窗累计受伤，短撤至附近安全处，脱险后恢复就近采矿；不能因观测频率高而忽略持续伤害。
2. 守矿分队应按当地威胁派出足够的反制单位，并明确与主军的交接；单个骚扰者不应把整军拉走，较大的远矿袭击也不能无人负责。
3. 扩张要有收入、路线和保护条件；为 MCV 存钱不能无限压掉必要的防御生产。
4. 进攻看局部血量、兵种、射程、塔区、地形和队形；撤退/转守要发出明确指令，停止生成新进攻单并不会取消旧单。
5. 侦察确认的暴露矿车、MCV 或远矿是机会；路线不安全、对方主军未定位或局部优势不足时，应放弃机会。

## 审计快照

以下七项均发现实际红警策略代码；是否采用这些提交参赛仍未知。

| 仓库 | 固定提交 | 主要读取文件 |
|---|---|---|
| henrysue/ucla-steve-nash-equilibrium | [6856a69d96d0][h-commit] | agent/redalert 下的决策、强度、侦察、袭击、驻军、扩张模块 |
| ryanxxhuang/altruagent-redalert | [f8fc888a509f][r-commit] | agent/redalert_bot.py |
| SirLinhart/PakledAgent | [2232a0e641e4][p-commit] | fight、base_defense、expansion、economy_hold、upkeep 及配置 |
| lukemt/friendly-fighter | [a11f16246096][f-commit] | agent/redalert_bot.py、docs/SPEED_LOOP.md |
| WilliamChenTW1209/altruagent-agent | [a62f763b49fa][w-commit] | examples/llm/redalert_autopilot.py |
| Khuongtdm/altruagent-entry | [0f9996b71a8e][k-commit] | redalert_policy.py，代码版本 ra-3.1 |
| lawrencedz/Riffo-Agent | [5c36414830d2][l-commit] | agent/agent.py，EconomyFirstRedAlert |

### Henry：保守主军、独立袭击队，远矿交接值得验证

**代码事实。** [brain][h-brain] / [commander][h-commander] 的常规攻击优势门槛为 1.3，7 分钟后降为 1.15；无绕路的窄口且攻城单位不足时再乘 1.5。已进攻的军队不会因低于发动门槛马上回家：通常强度跌破 0.8 才撤，交战前 15 秒或正在赚交换时可坚持到 0.5。另有亏交换触发：损失达到 max(1000, 进攻开始与当前军值较大者的25%)，且大于击杀的1.3倍。撤后通常冷却60秒，并要求军值增长30%；120秒后免增长要求。advisor、残局和压倒性优势有例外，这些不是每局固定时刻。

- [agent._believe][h-agent] 保留近期敌军峰值，并按自身军事投入推算未见敌军增长；不会把暂时看不见等同于没有军队。[strength][h-strength] 的主军估值按兵种完整 HP/DPS，不用当前血量、射程、装填和局部位置。因此“相同总军值”不代表相同战斗效果。
- [guard.Garrison.update][h-guard] 只给最新前置扩张最多2个步兵；后侧矿不在此驻军规则内。主力交战/进攻且该矿暂未见威胁时释放驻军；已受威胁时不会临时补招。配置另计划每扩张1座防御塔。
- [executor.army_contact / respond][h-executor]：主军接敌主要是主基地/主军附近、己方半场的大敌群；局部响应却跳过价值>1500的敌群，期待主军处理。因此距离主军远的扩张可能存在交接空隙，不能直接断言完全不设防。单兵诱出整军已有防护。
- [expand][h-expand] 在侦察及MCV生产前检查风险和军力，已进入 moving 后则持续到点、卡住另找部署位置，未再作路线威胁比较。前置MCV会阻止新主攻，也可能有小驻军，不是“裸开矿”。
- [raid.raid_spot][h-raid] 把当前可见与记忆敌军/炮塔直接拼接，未按ID去重；[memory.update / apply][h-memory] 又把当前可见对象包含在记忆中，可能重复计入袭击门槛。主军估值及 snipe 的目标区判断已去重，不能泛化。
- [snipe.orders][h-snipe] 攻击矿车后，原目标一旦不在“当前可见且距小队中心9格内”的矿车列表，就计一次击杀并离开，没有核实目标死亡。此队5:30后行动，盟军4–6辆轻车，苏军3辆重坦；发现我方主军已前压时，还会跳过定时袭击的目标区1.5倍优势检查。

**我方应对。** 主矿留适量反车辆保护；矿车用短撤与就近复采减少停工；从合法侦察发现的MCV/远矿选择局部优势机会，避免硬穿其窄口防线。小队击退后不应全军追逐。

**待验证。** 远矿1500阈值交接、MCV出发后的拦截、矿车短撤能否让 snipe 放弃，以及可见守军重复计数是否实际压制 raids。均可能被其塔、附近主军、原生自动攻击或其他模式抵消。

### Ryan：快速车辆骚扰遇到响应就退出

**代码事实。** [redalert_bot.py][r-code] 的 `_raid_view` 把小队9格内战斗单位、13格内正在接近的单位、射程加1.5格范围内的塔计为 responders。`_raid_phase_update` 中快速车辆队遇任何 responders、塔火力或超过5%的累计血量下降，就进入退出流程，然后可能换侧再来；步行队不同，要求响应强度超过自身1.2倍才因兵力撤退。`_strength` 是成本乘血量比例，残血保留5%估值地板，没有克制修正。

**我方应对。** 用足够自保的小矿卫覆盖矿路，在矿车与袭击车之间作局部响应；给追击设距离/时间上限。两侧矿路轮流遭袭时保持分工，不让主军反复换向。

**待验证。** 对快车队，1–2个有实际反制能力的守军能否稳定迫退；步行队不能套用同样结论。记录矿车停工、守军伤亡及袭击再入间隔，不能只记录“对面转头了”。

### Pakled：完整分层策略，关注储蓄与组成估值

**代码事实。** 该仓库有独立管理器、生产账本、迷雾记忆、矿车逃跑、塔区和围城处理，不是只转发LLM的薄壳。模型参与计划选择，但原始模型指令默认关闭。

- [fight._matchup][p-fight] 按“兵种集合是否包含反制类型”调整整组估值。敌军车辆价值占比超过60%、己方全是小口径步兵时整体乘0.5；加入一个不在该集合的火箭兵即可解除这层折扣，未按该兵的火力/血量贡献平滑调整。其其他战斗层仍有伤害、碾压和目标过滤，不能据此保证可诱骗。
- [expansion][p-expand] 的第二MCV默认5分钟到期；在有合格扩张条件、服务站、可生产MCV且无现成MCV时，仅 major 威胁排除需求。[upkeep][p-upkeep] 对该到期储蓄调用 `FullHold.holds(..., untimed=True)`，full_hold 使普通军队生产返回空；[economy_hold][p-hold] 的 untimed 不受通常的超时/释放窗口约束。
- [base_defense][p-defense] 的单个敌人且总成本≤600可判 minor；之前已升major则可能保持major。其已有矿车逃跑、守军和救援，minor 不等于无防御。

**我方应对。** 自身估值按每个单位可贡献的伤害、血量及反制占比平滑计算；扩张储蓄要给紧急反制留预算。对方已显露上述条件时，可测试低成本矿路骚扰带来的收入压力，不为“保持minor”牺牲我方安全。

**待验证。** 单Jeep在其5分钟第二MCV储蓄期间，是否能持续降低收入并延长普通军队停产。需要合格扩张地、未升级major等多项前提；占住扩张地或投入大军可能反而取消储蓄条件。另测“99步枪兵+1火箭兵”是否产生不合理估值跳变。

### Friendly-fighter：按波次出兵，转守不一定撤回旧单

**代码事实。** [redalert_bot.py][f-code] 的 `_attack` 默认首波等3辆车或360秒，并满足8个战斗单位门槛；后续门槛为8加2×min(已发波次,3)。波次存活数低于max(2, 记录的波次规模整除3)才结束，增援会更新该规模，发动条件未比较局部敌我强弱。防守姿态或最后60秒领先会直接返回，不在该分支发stop/召回指令，因此已有进攻命令可能继续。防守选最近威胁；有波次活动时主要抽家附近单位。

**我方应对。** 用队形、塔和局部兵力接住其波次，保留反击而非见兵即全冲；我方切转守时明确替换已有进攻单。观察其实际姿态，不假定永远采用默认attack。

**待验证。** 不同波次规模在塔前、窄口和开阔地的交换；“最后60秒停止新单但旧单仍执行”对实际交换有多大影响。其文档自报防守配置战绩属于作者实验，未在本次复现。

### William：经济门槛与可见数量捷径

**代码事实。** [redalert_autopilot.py][w-code] 的 `_defend` 对近6秒内本家或矿车受袭事件，最多调用前50个 `legal.combat_units`；这是合法空闲候选，不能说会拉走全部正在作战的军队。`crushing` 用己方战斗单位≥30且至少为当前可见敌数4倍判断压倒性，不在此判据中计算价值、血量、塔与迷雾。它可覆盖最后300秒领先>5000时的守成。`economy_ready` 要车厂、2炼厂和3矿车；跌至2矿车会暂时停用部分planner生产、专门矿卫和矿厂防御逻辑，但仍有基础防守、补车和步兵逻辑。

**我方应对。** 避免用无效牵制送分；在安全前提下优先保护自己的矿车并寻找其暴露矿车。对明显只按人数判断的进攻，以真实局部装甲/火力和塔区评估接战。

**待验证。** 少量暴露兵力加后方防线是否使其“压倒性”判断过度乐观；打掉第3辆矿车后经济/保护层多久恢复。不能把经济门槛缺口描述为整个bot停摆。

### Khuong：ra-3.1按规模进攻，近家响应范围较宽

**代码事实。** [redalert_policy.py][k-code] 的实际代码版本为ra-3.1，LLM仅给说明note，不参与规则决策，旧README不能代表当前行为。默认任意可见敌人距基地≤28格便触发防守，调基地42格内最多50名战斗单位；未在此触发条件区分侦察兵与主攻。默认24单位且6坦克发动主攻，600秒后20单位可免坦克要求；此门槛不比较敌力、塔和路线。已进攻状态通常到军数<6才清。最后150秒领先会禁止新攻，但既有 `_attacking` 分支仍可每15秒送出至少12个闲置援军。参数可调，不能把默认值当唯一部署配置。

**我方应对。** 我方近家防守按威胁规模、距离与资产价值派兵；侦察尽量保持存活，观察对方调动后再决定是否有安全的侧翼机会。防御其数量门槛冲锋时保持队形和反装甲配比。

**待验证。** 单侦察者是否造成有意义的生产区/矿区防守空隙，以及残局援军是否仍送进亏损战斗。仅看到其军队移动不等于牵制收益为正。

### Riffo：经济优先规则，有同批订单与同步模型风险

**代码事实。** [agent.py / EconomyFirstRedAlert][l-code] 的 `_ready_to_attack` 使用战斗数量+2×坦克数量，门槛13；要求炼厂，以及车厂或加权数量≥22。另与可见敌人的同类加权数量比较1.1倍，未在此门槛纳入塔、当前血量和迷雾记忆。近家16格内敌人可让前18个战斗单位接到防守attack；同一 `_build_plan` 随后仍可能添加 `legal.attack_now`，存在同单位订单重叠的可能，需观察实际合法批次。基地成形且本地计划没有attack时，约55秒一次、最多9次同步调用模型，调用在返回本地建造/生产计划之前，配置超时8秒；不能把注释“持续生产”理解为完全异步。

**我方应对。** 我方同一单位每轮只保留一个当前任务，紧急防守与撤退优先；关键经济与防守循环不等待模型。对其按数量发动的军队仍按真实局部优势接战。

**待验证。** 同批防守与进攻订单是否真的覆盖、哪些单位受影响；模型延迟是否造成可测的生产/响应空档。代码路径存在不等于每轮发生8秒停顿。

## 验证矩阵与结果边界

静态审计已完成。下表区分已完成的我方合成场景检查和仍需真实对局复验的假设。最终完整回归结果见 VALIDATION_V25.md。合成测试只证明给定观察下的行为，真实引擎与平台胜率另列。

| 项目 | 具体场景与需观察结果 | 当前证据/实际结果 |
|---|---|---|
| 七对手源码审计 | 以上固定提交、函数、默认配置与调用先后 | 已完成公开只读审计；未执行对手 |
| 持续小伤害 | 同样8秒累计伤害，低频与5Hz观察应作一致撤离；含不可见攻击者 | 已通过 test_mining_chip_damage_v25.py 的相应场景 |
| 误报与复采 | 零散旧伤、修复后新伤不错误累计；脱险后恢复近矿 | 已通过 test_mining_chip_damage_v25.py 的相应场景 |
| 矿卫与主军分工 | 1辆快车、多个袭击者、来回换侧；不全军追、不无人应援 | 我方合成场景已通过；完整对手未测 |
| 机会进攻边界 | 已见孤立MCV/矿车可考虑；护军、塔区、不可达路线出现则放弃 | 我方合成场景已通过；完整对手未测 |
| Henry远矿交接 | 固定地图与军队位置，比较价值1500上下袭击队的应援时间 | 未做对手真实引擎测试 |
| Henry短撤与MCV | 矿车移出9格/视野后是否取消snipe；MCV出发后出现路线威胁 | 未做对手真实引擎测试 |
| Ryan小矿卫 | 快车队遇局部守军后的退出/再入；与步行队对照 | 未做对手真实引擎测试 |
| Pakled储蓄 | 5分钟、单yard、可造MCV、正常扩张地、单Jeep压力；记录收入和停产时长 | 未做对手真实引擎测试 |
| 组成估值 | 30步枪加入1火箭面对7重坦，估值不能因出现一种反制单位而突然翻倍 | test_match_strategy_v25.py 对应估值场景通过；Pakled实战未测 |
| Friendly / Khuong残局 | 已有进攻命令时切入领先窗口，检查撤回与援军，而非仅看新单 | 未做对手真实引擎测试 |
| William / Riffo响应 | 第3矿车损失与恢复；同轮防守/进攻订单；模型延迟下队列空转 | 未做对手真实引擎测试 |
| v2.5相对v2.4 | 同地图、种子、座位互换、观察频率，保留失败与退步 | 未做本次真实引擎A/B对局 |
| 七对手胜率 | 固定双方版本与配置，足够配对样本，区分歼灭/到时计分 | 尚未建立，不能报告胜率或“最强” |

真实引擎验证至少记录：地图、种子、双方提交/配置、阵营与座位、观测节奏、游戏时长、胜负判据、击杀减损失、矿车存活、采矿停工、守军调动和命令拒绝。先复验机制，再测整局收益；同一战术在另一地图退步也应保留。现有本地单外部bot基准或合成订单测试，不应标成“对七名完整对手获胜”。

## 固定来源

[h-commit]: https://github.com/henrysue/ucla-steve-nash-equilibrium/commit/6856a69d96d0b86a7ab54fc51d29a7b2b833db61
[h-brain]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/brain.py
[h-commander]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/commander.py
[h-agent]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/agent.py
[h-strength]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/strength.py
[h-guard]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/guard.py
[h-executor]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/executor.py
[h-expand]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/expand.py
[h-raid]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/raid.py
[h-memory]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/memory.py
[h-snipe]: https://github.com/henrysue/ucla-steve-nash-equilibrium/blob/6856a69d96d0b86a7ab54fc51d29a7b2b833db61/agent/redalert/snipe.py
[r-commit]: https://github.com/ryanxxhuang/altruagent-redalert/commit/f8fc888a509f785c43f99164c78c67185ae147cc
[r-code]: https://github.com/ryanxxhuang/altruagent-redalert/blob/f8fc888a509f785c43f99164c78c67185ae147cc/agent/redalert_bot.py
[p-commit]: https://github.com/SirLinhart/PakledAgent/commit/2232a0e641e43d17515028359ef874431b909dcd
[p-fight]: https://github.com/SirLinhart/PakledAgent/blob/2232a0e641e43d17515028359ef874431b909dcd/src/ucla_agent/games/redalert/fight.py
[p-expand]: https://github.com/SirLinhart/PakledAgent/blob/2232a0e641e43d17515028359ef874431b909dcd/src/ucla_agent/games/redalert/expansion.py
[p-upkeep]: https://github.com/SirLinhart/PakledAgent/blob/2232a0e641e43d17515028359ef874431b909dcd/src/ucla_agent/games/redalert/upkeep.py
[p-hold]: https://github.com/SirLinhart/PakledAgent/blob/2232a0e641e43d17515028359ef874431b909dcd/src/ucla_agent/games/redalert/economy_hold.py
[p-defense]: https://github.com/SirLinhart/PakledAgent/blob/2232a0e641e43d17515028359ef874431b909dcd/src/ucla_agent/games/redalert/base_defense.py
[f-commit]: https://github.com/lukemt/friendly-fighter/commit/a11f1624609646d5dcbf0f6033677ee0f9fee244
[f-code]: https://github.com/lukemt/friendly-fighter/blob/a11f1624609646d5dcbf0f6033677ee0f9fee244/agent/redalert_bot.py
[w-commit]: https://github.com/WilliamChenTW1209/altruagent-agent/commit/a62f763b49facb7ec41d112a44c6d6e4369845e1
[w-code]: https://github.com/WilliamChenTW1209/altruagent-agent/blob/a62f763b49facb7ec41d112a44c6d6e4369845e1/examples/llm/redalert_autopilot.py
[k-commit]: https://github.com/Khuongtdm/altruagent-entry/commit/0f9996b71a8ee736a5a1163f64ed02790a381b63
[k-code]: https://github.com/Khuongtdm/altruagent-entry/blob/0f9996b71a8ee736a5a1163f64ed02790a381b63/redalert_policy.py
[l-commit]: https://github.com/lawrencedz/Riffo-Agent/commit/5c36414830d223a4e30d81f0220df30e6e150970
[l-code]: https://github.com/lawrencedz/Riffo-Agent/blob/5c36414830d223a4e30d81f0220df30e6e150970/agent/agent.py

