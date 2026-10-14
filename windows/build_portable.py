"""Cross-build a portable Windows launcher with an official Python runtime.

Inputs are already-downloaded official Python/PyPI archives. No Windows
binary is executed by this builder; build-info explicitly records that limit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

from windows.build import ROOT, validate_windows_pe


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unpack(archive: zipfile.ZipFile, destination: Path, *, wheel=False) -> None:
    for item in archive.infolist():
        if item.is_dir():
            continue
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in item.filename:
            raise RuntimeError("Unsafe archive path")
        if wheel and path.parts[0].endswith(".data"):
            if path.parts[1] not in {"purelib", "platlib"}:
                continue  # Console scripts and install-time helpers are unused.
            path = PurePosixPath(*path.parts[2:])
        target = destination.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(item))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--python-zip", required=True, type=Path)
    parser.add_argument("--wheels", required=True, type=Path)
    parser.add_argument("--wheel-verification", required=True, type=Path)
    parser.add_argument("--mingw-license", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subprocess.run(["git", "diff", "--exit-code", "HEAD"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    target = args.output.resolve() / "AltruAgentRedAlert"
    if target.exists():
        raise SystemExit("Use a fresh output directory so old runtime files cannot enter the bundle")
    target.mkdir(parents=True)
    runtime, app = target / "runtime", target / "app"
    with zipfile.ZipFile(args.python_zip) as archive:
        unpack(archive, runtime)
    validate_windows_pe(runtime / "python.exe")
    with zipfile.ZipFile(runtime / "python312.zip") as standard_library:
        assert "multiprocessing/spawn.pyc" in standard_library.namelist()
    (runtime / "python312._pth").write_text(
        "python312.zip\n.\nLib\\site-packages\n..\\app\nimport site\n", encoding="ascii")
    verified = json.loads(args.wheel_verification.read_text())
    wheels = sorted(args.wheels.glob("*.whl"))
    if len(wheels) != len(verified):
        raise RuntimeError("Wheel inventory differs from the verified manifest")
    for wheel in wheels:
        if verified[wheel.name]["sha256"] != digest(wheel):
            raise RuntimeError(f"Wheel hash mismatch: {wheel.name}")
        if not wheel.name.endswith(("-any.whl", "-win_amd64.whl")):
            raise RuntimeError("Only Windows x64 or platform-independent wheels are allowed")
        with zipfile.ZipFile(wheel) as archive:
            unpack(archive, runtime / "Lib" / "site-packages", wheel=True)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    prefixes = {"agent", "altruagent", "altru_redalert", "examples", "windows"}
    source_files = {}
    for raw in tracked:
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        if relative.parts[0] in prefixes and relative.suffix == ".py" and "tests" not in relative.parts:
            source = ROOT / relative
            destination = app / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            source_files[relative.as_posix()] = digest(source)
    executable = target / "AltruAgentRedAlert.exe"
    subprocess.run([str(args.compiler), "-municode", "-O2", "-s", "-Werror", "-static-libgcc",
                    "-Wl,--nxcompat,--dynamicbase", str(ROOT / "windows" / "native_launcher.c"),
                    "-o", str(executable)], check=True)
    validate_windows_pe(executable)
    probe = subprocess.run([sys.executable, "-m", "windows.entry", "--self-test", "--no-pause"],
                           cwd=ROOT, capture_output=True, text=True, timeout=90, check=True)
    report = json.loads(probe.stdout.strip().splitlines()[-1])
    assert report["ok"]
    (target / "source-self-test.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name in ("LICENSE", "SOURCES.md", "THIRD_PARTY_NOTICES.md"):
        if (ROOT / name).is_file():
            shutil.copy2(ROOT / name, target / name)
    shutil.copy2(ROOT / "windows" / "README_PORTABLE.txt", target / "README.txt")
    notices = target / "third-party-licenses"
    notices.mkdir()
    shutil.copy2(runtime / "LICENSE.txt", notices / "Python-LICENSE.txt")
    shutil.copy2(args.mingw_license, notices / "MinGW-runtime-copyright.txt")
    gcc_notice = args.compiler.resolve().parents[1] / "share" / "doc" / "gcc-mingw-w64-base" / "copyright"
    if gcc_notice.is_file():
        shutil.copy2(gcc_notice, notices / "GCC-runtime-copyright.txt")
    for license_file in (runtime / "Lib" / "site-packages").rglob("*"):
        if license_file.is_file() and any(p.endswith(".dist-info") for p in license_file.parts):
            if license_file.name.casefold().startswith(("license", "licence", "copying", "notice", "copyright", "authors")):
                relative = license_file.relative_to(runtime / "Lib" / "site-packages")
                output = notices / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(license_file, output)
    info = {
        "commit": commit, "source_published": False,
        "source_repository": "https://github.com/hehz2020/altruagent-redalert",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "format": "Windows x64 native console launcher + bundled official Python 3.12.10",
        "build_environment": "Linux with MinGW cross-compiler",
        "compiler": subprocess.check_output([str(args.compiler), "--version"], text=True).splitlines()[0],
        "windows_execution_verified": False,
        "validation": "PE x64 headers and source Python/controller/spawn/MCP checks only; Windows runtime execution not tested",
        "python_distribution": {"url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
                                "sha256": digest(args.python_zip)},
        "wheels": verified, "source_files_sha256": source_files,
        "launcher_sha256": digest(executable),
    }
    (target / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "archive", "--format=zip", "--prefix=source/", "-o",
                    str(target / "source-complete.zip"), commit], cwd=ROOT, check=True)
    files = sorted(p for p in target.rglob("*") if p.is_file())
    (target / "SHA256SUMS.txt").write_text("".join(f"{digest(p)}  {p.relative_to(target).as_posix()}\n" for p in files), encoding="utf-8")
    bundle = args.output.resolve() / "AltruAgentRedAlert-Windows-Portable.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in target.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(target.parent))
    (args.output / "SHA256SUMS.txt").write_text(f"{digest(bundle)}  {bundle.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(bundle), "commit": commit, "size": bundle.stat().st_size,
                      "sha256": digest(bundle), "windows_execution_verified": False}))


if __name__ == "__main__":
    main()
