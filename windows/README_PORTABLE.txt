AltruAgent Red Alert Bot — Windows 10/11 x64 便携版

请完整解压 ZIP，然后双击 AltruAgentRedAlert.exe。
必须保留旁边的 runtime 和 app 文件夹；不要只复制 EXE。
包内已包含 Python 和依赖，不需要另外安装 Python。

1. 选择模式：1 = 测试对局，2 = 正式比赛，3 = 两者，4 = 只检查连接。
2. 粘贴自己的 Official Agent Key。输入不显示，回车确认。
3. 保持窗口打开、电脑联网并处于唤醒状态。同一账号只启动一个程序。

测试：在平台创建或加入 Red Alert，对应席位选择 Mine (self-hosted)。
正式比赛：先在平台完成报名和 Self Hosted 配置，再选模式 2 或 3。
程序不会替你注册、创建比赛或改变平台账号设置。
按 Ctrl+C 停止。关闭窗口或电脑休眠会使机器人离线。

Key 不在安装包内，也不会由本程序写入磁盘。每次启动可重新输入。
可选：如果已有本机私密 .env，把它放在 EXE 旁边即可读取。
格式：ALTRUAGENT_OFFICIAL_AGENT_KEY=你的完整Key
不要上传或分享 .env。环境变量配置优先于 .env。

诊断（不联网、不需要 Key），在解压文件夹的终端运行：
  AltruAgentRedAlert.exe --self-test --no-pause

这个包的启动器是交叉编译生成的真实 Windows x64 EXE，运行时来自
Python 官方 Windows 发行包及 PyPI Windows 依赖。
已经检查 EXE 格式、依赖、文件哈希，并在 Linux 上验证策略和 Python 启动逻辑。
当前环境不能执行 Windows 程序，因此本便携版尚未在真实 Windows 上运行验证。
以上检查不代表比赛胜率或必胜保证。

app 文件夹包含本版本的运行源码。build-info.json 记录准确提交、依赖与验证范围。
source-complete.zip 包含这个提交的完整源码、测试和构建流程，供保存或上传 GitHub。
本版本是否已同步 GitHub，以 build-info.json 的 source_published 字段为准。

这是 Red Alert 专用策略；其他游戏需要单独配置备用策略。
脱敏游戏日志默认位于：%LOCALAPPDATA%\AltruAgentRedAlert\logs
源码仓库：https://github.com/hehz2020/altruagent-redalert
