"""Starts the packaged Style Atlas (the Windows zip or the Linux tar.gz).

Run by "Style Atlas.bat" or style-atlas.sh (with a console) and by the desktop shortcut (no
console). In order:
1. put a downloaded update in place (updates/ready: the program fetched and checked it after the
   user pressed Update);
2. install what the program needs into the bundled Python when it is missing or has changed (the
   first start: torch, about 2.5 GB with an NVIDIA card, 200 MB without; later only what an update
   adds), showing the progress in a console;
3. from the console: make (or refresh) the desktop shortcut, start the program on its own and let
   the console close; from the shortcut: start the program.
Only the standard library is used: the first time nothing else is installed yet."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
WINDOWS = sys.platform == "win32"
PY_DIR = ROOT / "python"
PYTHON = PY_DIR / ("python.exe" if WINDOWS else "bin/python3")
GUI_PYTHON = PY_DIR / "pythonw.exe" if WINDOWS else PYTHON
MARK = PY_DIR / "style-atlas-env.json"  # what was installed, so a change is noticed
UPDATES = ROOT / "updates"
READY = UPDATES / "ready"
PREVIOUS = UPDATES / "previous"  # the version before the last update, kept once
LOG = ROOT / "style-atlas.log"  # the program's messages when no console shows them
LOG_MAX = 5 * 1024 * 1024  # bytes; a bigger log is kept once as style-atlas.old.log
LOG_ENV = "STYLE_ATLAS_LOG"  # tells the program where its messages go
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu128",
    "cpu": "https://download.pytorch.org/whl/cpu",
}
TORCH_ENV = "STYLE_ATLAS_TORCH"  # "cpu" or "cuda": overrides the automatic choice
EXIT_WAIT = 60  # seconds to wait for the program being restarted to close
MAX_ROOT = 110  # torch's longest file (119) + python\Lib\site-packages\ must fit in 260 characters
CREATE_NEW_CONSOLE = 0x00000010
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def say(zh: str, en: str) -> None:
    print(f"{zh}\n{en}", flush=True)


# ---------- 1. a downloaded update ----------


def wait_for_exit(pid: int) -> None:
    """Wait until the program being restarted has closed (its files are then free to move)."""
    end = time.monotonic() + EXIT_WAIT
    while time.monotonic() < end and _alive(pid):
        time.sleep(0.3)


def _alive(pid: int) -> bool:
    if WINDOWS:
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def apply_update() -> None:
    """Swap updates/ready in for app/ (and launch.py); the old app/ is kept as updates/previous."""
    if not (READY / "app" / "styleatlas" / "__init__.py").is_file():
        return
    shutil.rmtree(PREVIOUS, ignore_errors=True)
    PREVIOUS.mkdir(parents=True)
    if APP.exists():
        APP.rename(PREVIOUS / "app")
    (READY / "app").rename(APP)
    new_launcher = READY / "launch.py"
    if new_launcher.is_file():  # this file is read already: replacing it is safe
        shutil.copy2(ROOT / "launch.py", PREVIOUS / "launch.py")
        shutil.copy2(new_launcher, ROOT / "launch.py")
    shutil.rmtree(READY, ignore_errors=True)


# ---------- 2. the packages the program needs ----------


def _digest(*paths: Path) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(path.read_bytes() if path.is_file() else b"")
    return h.hexdigest()


def torch_variant(have: dict) -> str:
    """The torch build to have: the one asked for, else the one installed, else by the GPU."""
    forced = os.environ.get(TORCH_ENV, "").strip().lower()
    if forced in TORCH_INDEX:
        return forced
    if have.get("torch") in TORCH_INDEX:
        return have["torch"]
    return "cuda" if shutil.which("nvidia-smi") else "cpu"


def wanted(have: dict) -> dict:
    return {
        "torch": torch_variant(have),
        "torch_pins": _digest(APP / "requirements-torch.txt"),
        "packages": _digest(APP / "requirements.txt", APP / "constraints.txt"),
    }


def installed() -> dict:
    try:
        return json.loads(MARK.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def ready() -> bool:
    have = installed()
    return have == wanted(have)


def path_fits() -> bool:
    """Whether torch's files fit under this folder (Windows without long paths: 260 characters)."""
    if not WINDOWS or len(str(ROOT)) <= MAX_ROOT:
        return True
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def pip(*args: str) -> bool:
    command = [str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check"]
    return subprocess.run([*command, "--no-warn-script-location", *args]).returncode == 0


def prepare() -> bool:
    """Install torch and the rest into the bundled Python; True when everything went in."""
    have = installed()
    want = wanted(have)
    if have.get("torch") != want["torch"] or have.get("torch_pins") != want["torch_pins"]:
        size = "约 2.5 GB" if want["torch"] == "cuda" else "约 200 MB"
        size_en = "about 2.5 GB" if want["torch"] == "cuda" else "about 200 MB"
        kind = "NVIDIA 显卡版" if want["torch"] == "cuda" else "CPU 版"
        say(
            f"正在下载并安装 torch（{kind}，{size}），只有第一次需要，请稍候…",
            f"Downloading and installing torch ({want['torch']}, {size_en}); only the first time…",
        )
        pins = ["-r", str(APP / "requirements-torch.txt")]
        if not pip(*pins, "--index-url", TORCH_INDEX[want["torch"]]):
            return False
    say("正在安装其余需要的套件…", "Installing the other packages…")
    reqs = ["-r", str(APP / "requirements.txt"), "-c", str(APP / "constraints.txt")]
    if not pip(*reqs):
        return False
    MARK.write_text(json.dumps(want), "utf-8")
    say("环境准备好了。", "Ready.")
    return True


# ---------- 3. the shortcut and the program ----------


def has_console() -> bool:
    """Whether a console shows this process's messages. On Windows the NUL device counts as a
    terminal for isatty(), so ask for the console window itself."""
    if sys.stdout is None or sys.stdin is None:
        return False
    if WINDOWS:
        import ctypes

        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    return sys.stdin.isatty()


def open_console(args: list[str]) -> None:
    """Run this file again where the user can see the progress (a new console)."""
    command = [str(PYTHON), str(ROOT / "launch.py"), *args]
    if WINDOWS:
        subprocess.Popen(command, creationflags=CREATE_NEW_CONSOLE, cwd=ROOT)
        return
    for terminal in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
        if shutil.which(terminal):
            subprocess.Popen([terminal, "-e", *command], cwd=ROOT)
            return
    with LOG.open("a", encoding="utf-8") as log:  # no terminal: work quietly into the log
        subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)


def start_detached(args: list[str]) -> None:
    """Start the program on its own, so the console can close (it writes into the log)."""
    command = [str(GUI_PYTHON), str(ROOT / "launch.py"), "--run", *args]
    quiet = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if WINDOWS:
        subprocess.Popen(command, creationflags=DETACHED, cwd=Path.home(), **quiet)
    else:
        subprocess.Popen(command, cwd=Path.home(), start_new_session=True, **quiet)


def log_to_file() -> None:
    """Without a console, the program's progress and errors go to style-atlas.log (a console
    that was closed would make every message fail)."""
    if LOG.exists() and LOG.stat().st_size > LOG_MAX:
        LOG.replace(LOG.with_name("style-atlas.old.log"))
    stream = open(LOG, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the program
    sys.stdout = sys.stderr = stream
    os.environ[LOG_ENV] = str(LOG)


def use_app() -> None:
    os.environ["STYLE_ATLAS_PACKAGE"] = str(ROOT)
    sys.path.insert(0, str(APP))


def make_shortcut() -> None:
    use_app()
    from styleatlas.shortcut import make_package_shortcut

    try:
        where = make_package_shortcut(ROOT, GUI_PYTHON)
    except (OSError, subprocess.SubprocessError) as e:
        say(f"没能建立快捷方式（{e}）。", f"Could not make the shortcut ({e}).")
        return
    say(f"快捷方式：{where}", f"Shortcut: {where}")


def run(folder: list[str]) -> int:
    if not has_console():
        log_to_file()
    use_app()
    from styleatlas.desktop import main as desktop_main

    return desktop_main(folder)


def main(argv: list[str]) -> int:
    run_now = "--run" in argv
    args = [a for a in argv if a != "--run"]
    if "--after" in args:
        at = args.index("--after")
        wait_for_exit(int(args[at + 1]))
        del args[at : at + 2]
    apply_update()
    console = has_console()
    if not ready():
        if not console:
            open_console(args)
            return 0
        if not path_fits():
            say(
                f"这个文件夹的路径太长（{len(str(ROOT))} 个字符），Windows 放不下 torch 的文件。"
                "请把 StyleAtlas 文件夹搬到短一点的位置（例如 D:\\StyleAtlas），再双击一次。",
                f"This folder's path is too long ({len(str(ROOT))} characters) for torch's files "
                "on Windows. Move the StyleAtlas folder somewhere shorter (e.g. D:\\StyleAtlas) "
                "and double-click again.",
            )
            input("按 Enter 关闭 / Press Enter to close ")
            return 1
        if not prepare():
            say(
                "安装没有完成（网络断了？）。再双击一次会接着装。",
                "The install did not finish (network?). Double-click again to continue.",
            )
            input("按 Enter 关闭 / Press Enter to close ")
            return 1
    if console and not run_now:
        make_shortcut()
        start_detached(args)
        say("Style Atlas 已经启动，这个窗口会自己关闭。", "Style Atlas is starting.")
        time.sleep(2)
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
