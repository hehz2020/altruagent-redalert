"""Console launcher, bundled with Python; no credential is built into the EXE."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import warnings

KEY_ENV = "ALTRUAGENT_OFFICIAL_AGENT_KEY"
KEY_PATTERN = re.compile(r"eak_live_[0-9a-f]{64}\Z")
MODES = {
    "testing": ["--match"],
    "tournament": ["--tournament"],
    "both": ["--tournament", "--match"],
    "check": ["--check-tournament"],
}


def valid_key(value: object) -> bool:
    return isinstance(value, str) and KEY_PATTERN.fullmatch(value.strip()) is not None


def application_directory() -> Path:
    # The portable native launcher supplies this directory while Python runs
    # from the adjacent runtime folder. PyInstaller does not need this value.
    if os.environ.get("ALTRUAGENT_LAUNCHER_ROOT"):
        return Path(os.environ["ALTRUAGENT_LAUNCHER_ROOT"]).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def configure_environment(root: Path) -> None:
    # Read only the intentional .env beside the program, never a parent
    # directory picked by find_dotenv. Never overwrite an inherited setting.
    from dotenv import dotenv_values

    env_file = root / ".env"
    if env_file.is_file():
        for key, value in dotenv_values(env_file, encoding="utf-8-sig").items():
            if value is not None:
                os.environ.setdefault(key, value)
    os.environ.setdefault("ALTRUAGENT_CONTROL_URL", "https://api.altruagent-game.com")
    os.environ.setdefault("ALTRUAGENT_PERSISTENT_MCP", "1")
    # Per-user writable location also works when the EXE is in a protected
    # folder. The controller writes only sanitized gameplay observations.
    data_root = Path(os.environ.get("LOCALAPPDATA") or root) / "AltruAgentRedAlert"
    os.environ.setdefault("REDALERT_LOG_DIR", str(data_root / "logs"))


def prepare_key() -> None:
    if valid_key(os.environ.get(KEY_ENV)):
        os.environ[KEY_ENV] = os.environ[KEY_ENV].strip()
        print("已读取本机配置的 Official Agent Key。")
        return
    print("请粘贴 Official Agent Key。输入不会显示；本次输入只保存在运行内存中。")
    for _ in range(3):
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                value = getpass.getpass("Official Agent Key: ").strip()
            except getpass.GetPassWarning as exc:
                raise RuntimeError("此终端不支持隐藏输入，请直接双击 EXE 重试。") from exc
        if valid_key(value):
            os.environ[KEY_ENV] = value
            return
        print("Key 格式不正确，请复制完整的 Official Agent Key 再试一次。")
    raise RuntimeError("未输入有效的 Official Agent Key。")


def choose_mode() -> str:
    print("\n请选择运行模式：")
    print("  1. Testing 测试对局（直接回车选择此项）")
    print("  2. Tournament 正式比赛")
    print("  3. 同时接收测试对局和正式比赛")
    print("  4. 只检查连接，不参加对局")
    choices = {"": "testing", "1": "testing", "2": "tournament", "3": "both", "4": "check"}
    for _ in range(3):
        value = input("输入 1 / 2 / 3 / 4: ").strip()
        if value in choices:
            return choices[value]
        print("请输入 1、2、3 或 4。")
    raise RuntimeError("未选择有效模式。")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AltruAgent Red Alert Windows bot")
    parser.add_argument("--mode", choices=tuple(MODES), help="run without the mode menu")
    parser.add_argument("--self-test", action="store_true", help="offline controller + spawned-worker check")
    parser.add_argument("--no-pause", action="store_true", help="exit immediately when stopped")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args.self_test:
        from windows.selftest import run_self_test

        result = run_self_test()
        print(json.dumps(result, ensure_ascii=True), flush=True)
        return 0 if result.get("ok") else 1

    interactive = args.mode is None and not args.no_pause
    try:
        print("AltruAgent Red Alert Bot | Windows x64\n")
        configure_environment(application_directory())
        mode = args.mode or choose_mode()
        prepare_key()
        from agent.__main__ import main as run_agent

        if mode != "check":
            print("\n正在检查连接……此步骤不会注册或创建比赛。", flush=True)
            result = run_agent(["--check-tournament", "--agent", "altru_redalert"])
            if result:
                return result
            print("\n启动机器人。请保持电脑联网、唤醒，并保持此窗口打开。")
            print("同一账号只启动一个程序。按 Ctrl+C 停止。")
            print("在平台选择 Red Alert，席位选择 Mine (self-hosted)。", flush=True)
        return run_agent([*MODES[mode], "--agent", "altru_redalert"])
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0
    except EOFError:
        print("\n输入已关闭。请双击程序重新启动。")
        return 1
    except (OSError, RuntimeError) as exc:
        # Launcher errors contain no entered key; SDK errors are handled by
        # the official CLI. Do not dump the environment or HTTP headers.
        print(f"\n启动失败：{exc}")
        return 1
    finally:
        if interactive:
            try:
                input("\n按回车关闭窗口……")
            except (EOFError, KeyboardInterrupt):
                pass
