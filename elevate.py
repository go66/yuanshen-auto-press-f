
import os
import subprocess
import sys


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_target():
    """Return the (executable, argument string) pair used to relaunch elevated.

    The two launch modes are very different and must be handled separately:

    - Source run (`python main.py` / `uv run main.py`): sys.argv[0] is a .py file, so
      the current interpreter (sys.executable -- under uv that is the venv python) has
      to be told to execute it;
    - Installed run (`uvx` / `uv tool install` / pip): sys.argv[0] is the generated
      launcher. Careful: it **may have no .exe suffix** (uv's launcher reports a bare
      name such as `Scripts\\auto-press-f`, while the real file next to it is
      auto-press-f.exe), so checking the suffix alone is not enough -- probe the file
      system for the .exe. Executing that exe directly keeps us in the same environment.
    """
    script = sys.argv[0] or ""
    args = sys.argv[1:]
    if not script:
        return sys.executable, subprocess.list2cmdline(args)

    is_py = script.lower().endswith(".py")
    exe = script if script.lower().endswith(".exe") else script + ".exe"
    if not is_py and os.path.isfile(exe):
        return os.path.abspath(exe), subprocess.list2cmdline(args)
    return sys.executable, subprocess.list2cmdline([os.path.abspath(script)] + args)


def run_as_admin():
    import ctypes
    from ctypes import wintypes as wt

    exe, params = relaunch_target()
    # Relaunch in the current working directory: locating the config file depends on it,
    # and changing it would lose the user's existing settings.
    cwd = os.getcwd()
    se = ctypes.windll.shell32.ShellExecuteW
    se.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR,
                   wt.LPCWSTR, wt.INT]
    se.restype = ctypes.c_void_p
    return se(None, "runas", exe, params, cwd, 1)


def _say(msg):
    """Under pythonw sys.stdout is None, so a plain print() raises AttributeError."""
    try:
        if sys.stdout is not None:
            print(msg)
    except Exception:
        pass


def _log(msg):
    """GUI builds have no console, so elevation results (denials especially) go to the log."""
    try:
        from auto_press_f import CONFIG_PATH
        path = os.path.join(os.path.dirname(CONFIG_PATH), "auto_press_f.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("[elevate] %s\n" % msg)
    except Exception:
        pass


def ensure_admin():
    if sys.platform != "win32":
        return
    if is_admin():
        return
    _say("Requesting administrator privileges…")
    _log("requesting elevation: %r" % (relaunch_target(),))
    rc = run_as_admin()
    ok = rc is not None and int(rc) > 32
    if ok:
        sys.exit(0)
    _log("elevation failed (rc=%r)" % (rc,))
    sys.exit("Administrator privileges required (UAC denied or failed); exiting.")
