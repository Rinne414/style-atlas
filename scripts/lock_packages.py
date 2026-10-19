"""Write packaging/locks/: every package the packaged program installs, pinned with its SHA256.

The launcher installs with `pip --require-hashes` from these files, so a mirror (Tsinghua, NJU,
...) can only hand over the exact files tested here. One file per platform and step:
<platform>-torch-<cuda|cpu>.txt (from download.pytorch.org) and <platform>-packages.txt (from
PyPI, torch itself left out: the first step installed it). Each file starts with the digest of
the lists it was made from; build_release.py refuses a lock that no longer matches them.

Needs uv. Run after changing requirements*.txt or constraints.txt:
    python scripts/lock_packages.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGING = REPO / "packaging"
LOCKS = PACKAGING / "locks"
PYTHON = "3.13"
PLATFORMS = {"windows": "x86_64-pc-windows-msvc", "linux": "x86_64-manylinux_2_28"}
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu128",
    "cpu": "https://download.pytorch.org/whl/cpu",
}
PYPI = "https://pypi.org/simple"
SKIP_IN_PACKAGES = ("torch", "torchvision")  # installed by the torch step
DIGEST_MARK = "# inputs: "


def inputs_digest(*names: str) -> str:
    h = hashlib.sha256()
    for name in names:
        h.update((PACKAGING / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def torch_inputs() -> str:
    return inputs_digest("requirements-torch.txt")


def packages_inputs() -> str:
    return inputs_digest("requirements.txt", "constraints.txt")


def lock_names() -> list[tuple[str, str]]:
    """(file name, inputs digest it must carry) for every lock file."""
    names = []
    for platform in PLATFORMS:
        names += [(f"{platform}-torch-{variant}.txt", torch_inputs()) for variant in TORCH_INDEX]
        names.append((f"{platform}-packages.txt", packages_inputs()))
    return names


def stale() -> list[str]:
    """The lock files that are missing or were made from other package lists."""
    problems = []
    for name, digest in lock_names():
        path = LOCKS / name
        first = path.read_text("utf-8").splitlines()[0] if path.is_file() else ""
        if first != f"{DIGEST_MARK}{digest}":
            problems.append(name)
    return problems


def compile_lock(args: list[str], out: Path, digest: str, note: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "lock.txt"
        command = ["uv", "pip", "compile", *args, "--python-version", PYTHON]
        command += ["--generate-hashes", "--no-header", "--no-annotate", "-q", "-o", str(raw)]
        subprocess.run(command, check=True, cwd=REPO)
        body = raw.read_text("utf-8")
    header = f"{DIGEST_MARK}{digest}\n# {note}; made by scripts/lock_packages.py, do not edit\n"
    out.write_text(header + body, "utf-8", newline="\n")
    print(f"wrote {out.relative_to(REPO)}")


def main() -> int:
    LOCKS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        overrides = Path(tmp) / "overrides.txt"
        overrides.write_text(
            "".join(f'{name}; sys_platform == "never"\n' for name in SKIP_IN_PACKAGES), "utf-8"
        )
        for platform, triple in PLATFORMS.items():
            for variant, index in TORCH_INDEX.items():
                compile_lock(
                    ["packaging/requirements-torch.txt", "--python-platform", triple]
                    + ["--index-url", index],
                    LOCKS / f"{platform}-torch-{variant}.txt",
                    torch_inputs(),
                    f"torch ({variant}) for {platform}",
                )
            compile_lock(
                ["packaging/requirements.txt", "-c", "packaging/constraints.txt"]
                + ["--override", str(overrides), "--python-platform", triple]
                + ["--index-url", PYPI],
                LOCKS / f"{platform}-packages.txt",
                packages_inputs(),
                f"the other packages for {platform}",
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
