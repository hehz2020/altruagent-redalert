from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata, is_module_or_submodule

root = Path(SPECPATH).parent
hidden = []
for package in ("altruagent", "altru_redalert", "agent", "examples", "windows"):
    hidden += collect_submodules(package)
hidden += collect_submodules(
    "mcp", filter=lambda name: not is_module_or_submodule(name, "mcp.cli")
)

a = Analysis(
    [str(root / "windows" / "entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=copy_metadata("mcp", recursive=True),
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "mcp.cli"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="AltruAgentRedAlert", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, disable_windowed_traceback=False,
)
