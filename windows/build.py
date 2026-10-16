from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def license_entries(distributions) -> tuple[list[tuple[Path, str]], list[dict]]:

    entries: list[tuple[Path, str]] = []
    index: list[dict] = []
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("The Windows Python distribution's LICENSE.txt is missing")
    entries.append((python_license, "third-party-licenses/Python/LICENSE.txt"))
    for distribution in distributions:
        name = distribution.metadata.get("Name", "unknown")
        directory = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        copied = []
        for item in distribution.files or ():
            parts = item.parts
            info_at = next((i for i, part in enumerate(parts) if part.endswith(".dist-info")), None)
            if info_at is None or ".." in parts:
                continue
            basename = item.name.casefold()
            if not basename.startswith(("license", "licence", "copying", "notice", "copyright", "authors")):
                continue
            source = Path(distribution.locate_file(item))
            if not source.is_file():
                continue
            suffix = "/".join(parts[info_at + 1:])
            target = f"third-party-licenses/{directory}/{suffix}"
            entries.append((source, target))
            copied.append(target)
        index.append({"distribution": name, "version": distribution.version,
                      "license_expression": distribution.metadata.get("License-Expression", ""),
                      "license_metadata": distribution.metadata.get("License", ""),
                      "files": sorted(copied)})
    return entries, sorted(index, key=lambda row: row["distribution"].casefold())


def validate_windows_pe(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise RuntimeError("The build is not a Windows executable")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664:
        raise RuntimeError("The executable is not Windows PE x64")


def main() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Build on Windows x64. PyInstaller does not cross-compile Windows EXEs.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "windows/AltruAgentRedAlert.spec"], cwd=ROOT, check=True)
    executable = ROOT / "dist" / "AltruAgentRedAlert.exe"
    validate_windows_pe(executable)
    environment = os.environ.copy()
    for name in ("ALTRUAGENT_OFFICIAL_AGENT_KEY", "OPENAI_API_KEY", "ALTRUAGENT_API_KEY"):
        environment.pop(name, None)
    environment["PYTHONIOENCODING"] = "utf-8"
    tested = subprocess.run([str(executable), "--self-test", "--no-pause"],
                            cwd=ROOT, env=environment, capture_output=True,
                            text=True, encoding="utf-8", timeout=90, check=False)
    if tested.returncode:
        print(tested.stdout, end="", flush=True)
        print(tested.stderr, end="", file=sys.stderr, flush=True)
        tested.check_returncode()
    report = json.loads(tested.stdout.strip().splitlines()[-1])
    if not report.get("ok") or not report.get("frozen") or report.get("platform") != "win32":
        raise RuntimeError("Frozen Windows self-test failed")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    commit = os.environ.get("ALTRU_BUILD_COMMIT") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Build source commit must be a full Git SHA")
    build_environment = os.environ.get("ALTRU_BUILD_ENV", "Native Windows")
    distributions = list(metadata.distributions())
    packages = sorted({f"{item.metadata['Name']}=={item.version}" for item in distributions})
    licenses, license_index = license_entries(distributions)
    info = {
        "source_repository": "https://github.com/hehz2020/altruagent-redalert",
        "commit": commit, "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "architecture": "Windows x64", "dependencies": packages,
        "build_environment": build_environment,
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "validation": ("Actual Windows PE executable: offline controller, spawned worker and persistent MCP passed; "
                       f"tested in {build_environment}"),
    }
    (release / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    (release / "self-test.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(executable, release / executable.name)
    bundle = release / "AltruAgentRedAlert-Windows-x64.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(executable, executable.name)
        archive.write(ROOT / "windows" / "README.txt", "README.txt")
        archive.write(release / "build-info.json", "build-info.json")
        archive.write(release / "self-test.json", "self-test.json")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "SOURCES.md",
                     "BENCHMARK.md", "BENCHMARK_RESULTS.json", "VALIDATION_V24.md", "VALIDATION_V25.md"):
            path = ROOT / name
            if path.is_file():
                archive.write(path, name)
        for source, target in licenses:
            archive.write(source, target)
        archive.writestr("third-party-licenses/INDEX.json", json.dumps(license_index, indent=2) + "\n")
    checksums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                        for p in (release / executable.name, bundle, release / "build-info.json", release / "self-test.json"))
    (release / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
    print(json.dumps({"commit": commit, "executable": str(executable), "zip": str(bundle), "self_test": "passed"}))


if __name__ == "__main__":
    main()
