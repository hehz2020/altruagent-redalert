AltruAgent Red Alert Bot — Windows 10/11 x64

不需要安装 Python。

更新到 v2.3：先结束当前对局，再关闭旧机器人窗口，解压并启动新程序。
启动首行应显示 Bot v2.3。同一账号不要同时运行新旧程序。

这一版采用双矿厂与提前出坦克的开局，主力沿可达路径分段推进；
强攻不利时整队取消追击，避免坦克脱离步兵支援继续冲塔。
坦克核心形成后优先恢复少量步枪兵与反步兵车，再继续补坦克。
实际本地引擎对照结果见包内 BENCHMARK.md，包含失败记录；
这些成绩不是平台比赛胜率。

1. 解压整个 ZIP，然后双击 AltruAgentRedAlert.exe。
2. 选择模式：1 = 测试对局，2 = 正式比赛，3 = 两者，4 = 只检查连接。
3. 粘贴自己的 Official Agent Key。输入不显示，回车确认。
4. 保持窗口打开、电脑联网并处于唤醒状态。同一账号只启动一个程序。

测试：在平台创建或加入 Red Alert，对应席位选择 Mine (self-hosted)。
正式比赛：先在平台完成所需的报名和 Self Hosted 配置，再选模式 2 或 3。
程序不会替你注册、创建比赛或改变平台账号设置。
按 Ctrl+C 停止机器人。关闭窗口或电脑休眠会使机器人离线。

Key 不在安装包内，也不会由本程序写入磁盘。每次启动可重新输入。
可选：如果你已有本机私密 .env，把它放在 EXE 旁边即可读取。
格式：ALTRUAGENT_OFFICIAL_AGENT_KEY=你的完整Key
不要上传或分享 .env。环境变量配置优先于 .env。

诊断命令（不联网、不需要 Key）：
  AltruAgentRedAlert.exe --self-test --no-pause

命令行模式：
  AltruAgentRedAlert.exe --mode testing --no-pause
  AltruAgentRedAlert.exe --mode tournament --no-pause

这是 Red Alert 专用策略。其他游戏的默认备用策略需要单独的模型配置。
机器人胜率取决于对手、地图和网络状态；发布检查不等于比赛胜率测试。

脱敏游戏日志默认位于：%LOCALAPPDATA%\AltruAgentRedAlert\logs
源码与版本：https://github.com/hehz2020/altruagent-redalert
构建所用提交与依赖见 build-info.json；SHA256SUMS.txt 用于文件校验。
