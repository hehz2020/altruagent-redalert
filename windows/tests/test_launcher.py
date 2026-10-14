from pathlib import Path
import struct

import pytest

from windows import launcher
from windows.build import validate_windows_pe


def test_portable_launcher_reads_configuration_beside_exe(monkeypatch, tmp_path):
    monkeypatch.setenv("ALTRUAGENT_LAUNCHER_ROOT", str(tmp_path))
    assert launcher.application_directory() == tmp_path.resolve()


def test_key_prompt_stays_in_memory(monkeypatch, tmp_path, capsys):
    key = "eak_live_" + "a" * 64
    monkeypatch.delenv(launcher.KEY_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.getpass, "getpass", lambda _: key)
    launcher.prepare_key()
    assert launcher.os.environ[launcher.KEY_ENV] == key
    assert not list(tmp_path.iterdir())
    assert key not in capsys.readouterr().out


def test_existing_config_is_read_without_overwriting_environment(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("ALTRUAGENT_OFFICIAL_AGENT_KEY=old\nALTRUAGENT_PERSISTENT_MCP=0\n", encoding="utf-8")
    monkeypatch.setenv(launcher.KEY_ENV, "current")
    monkeypatch.setenv("ALTRUAGENT_PERSISTENT_MCP", "1")
    monkeypatch.delenv("REDALERT_LOG_DIR", raising=False)
    launcher.configure_environment(tmp_path)
    assert launcher.os.environ[launcher.KEY_ENV] == "current"
    assert launcher.os.environ["ALTRUAGENT_PERSISTENT_MCP"] == "1"
    assert launcher.os.environ["REDALERT_LOG_DIR"].endswith("logs")
    assert "old" in (tmp_path / ".env").read_text()


def test_tournament_mode_is_explicit(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert launcher.choose_mode() == "testing"
    monkeypatch.setattr("builtins.input", lambda _: "2")
    assert launcher.choose_mode() == "tournament"
    assert launcher.MODES["testing"] == ["--match"]


def test_pe_validator_rejects_renamed_non_windows_binary(tmp_path):
    path = tmp_path / "not-windows.exe"
    path.write_bytes(b"\x7fELF" + b"\x00" * 100)
    with pytest.raises(RuntimeError):
        validate_windows_pe(path)


def test_pe_validator_checks_architecture(tmp_path):
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, 0x8664)
    path = tmp_path / "test.exe"
    path.write_bytes(data)
    validate_windows_pe(path)
