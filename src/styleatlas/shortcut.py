"""Shortcuts that start Style Atlas without a console: a .lnk on the Windows desktop, or an entry
in the Linux application menu. `make_shortcut` serves a source checkout (scripts/setup.bat),
`make_package_shortcut` the packaged program (packaging/launch.py). STYLE_ATLAS_SHORTCUT_DIR puts
them in another folder (tests)."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib import resources
from pathlib import Path

NAME = "Style Atlas"
ICON = "data/style-atlas.ico"
LINUX_ICON = "style-atlas.png"  # next to launch.py in the Linux package
DIR_ENV = "STYLE_ATLAS_SHORTCUT_DIR"


def icon_path() -> Path:
    return Path(str(resources.files("styleatlas").joinpath(ICON)))


def make_shortcut(desktop_dir: Path | None = None) -> Path:
    """A desktop shortcut that starts this checkout's program (Windows)."""
    if sys.platform != "win32":
        raise OSError("shortcuts are made on Windows only")
    target = Path(sys.executable).parent / "pythonw.exe"
    if not target.exists():
        target = Path(sys.executable)
    folder = desktop_dir or _desktop_folder()
    return _windows_link(folder / f"{NAME}.lnk", target, "-m styleatlas.desktop")


def make_package_shortcut(root: Path, gui_python: Path) -> Path:
    """The packaged program's shortcut: on the desktop (Windows) or in the application menu."""
    launcher = root / "launch.py"
    if sys.platform == "win32":
        return _windows_link(_desktop_folder() / f"{NAME}.lnk", gui_python, f'"{launcher}"')
    return _linux_entry(gui_python, launcher, root / LINUX_ICON)


def _windows_link(link: Path, target: Path, arguments: str) -> Path:
    """The paths reach PowerShell through the environment, never through the command text."""
    env = {
        **os.environ,
        "SA_LINK": str(link),
        "SA_TARGET": str(target),
        "SA_ARGS": arguments,
        "SA_ICON": str(icon_path()),
        "SA_DIR": str(Path.home()),
    }
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SA_LINK); "
        "$s.TargetPath = $env:SA_TARGET; $s.Arguments = $env:SA_ARGS; "
        "$s.IconLocation = $env:SA_ICON; $s.WorkingDirectory = $env:SA_DIR; "
        "$s.Description = 'Style Atlas'; $s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        check=True,
        capture_output=True,
    )
    return link


def _linux_entry(python: Path, launcher: Path, icon: Path) -> Path:
    """A freedesktop.org menu entry (GNOME, KDE, Xfce...)."""
    override = os.environ.get(DIR_ENV)
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    folder = Path(override) if override else data / "applications"
    folder.mkdir(parents=True, exist_ok=True)
    entry = folder / "style-atlas.desktop"
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAME}\n"
        "Comment=Group pictures by art style, find similar styles, prepare LoRA sets\n"
        "Comment[zh_CN]=按画风整理图片、找相近画风、整理 LoRA 训练集\n"
        f"Exec={_exec_arg(python)} {_exec_arg(launcher)}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Graphics;Viewer;\n",
        "utf-8",
    )
    entry.chmod(0o755)
    return entry


def _exec_arg(path: Path) -> str:
    """One quoted Exec argument: the quoting rules first, then the desktop-entry string escape."""
    text = str(path)
    for ch in ("\\", '"', "`", "$"):
        text = text.replace(ch, "\\" + ch)
    return '"' + text.replace("\\", "\\\\") + '"'


def _desktop_folder() -> Path:
    """The user's desktop folder (it may have been moved, e.g. into OneDrive)."""
    if os.environ.get(DIR_ENV):
        return Path(os.environ[DIR_ENV])
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Environment]::GetFolderPath('Desktop')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    text = out.stdout.strip()
    return Path(text) if text and Path(text).is_dir() else Path.home() / "Desktop"
