
import ctypes
import ctypes.wintypes as wt
import json
import os
import random
import threading
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

VK_F = 0x46

_ULONG_PTR = (ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8
              else ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", _ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT
user32.MapVirtualKeyW.argtypes = (wt.UINT, wt.UINT)
user32.MapVirtualKeyW.restype = wt.UINT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = (wt.HWND,)
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = (wt.HWND,)
user32.IsWindowVisible.restype = wt.BOOL
user32.IsWindow.argtypes = (wt.HWND,)
user32.IsWindow.restype = wt.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wt.LPARAM)
user32.EnumWindows.restype = wt.BOOL


def _make_key_input(scan_code: int, flags: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(0, scan_code, flags, 0, 0)
    return inp


WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

METHODS = {
    "scan": "SendInput + scancode",
    "vk": "SendInput + virtual key",
    "keybd": "keybd_event + scancode",
    "post": "PostMessage to main window",
    "post_child": "PostMessage to child window",
}

user32.PostMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.PostMessageW.restype = wt.BOOL
user32.keybd_event.argtypes = (ctypes.c_ubyte, ctypes.c_ubyte, wt.DWORD,
                               ctypes.c_ulonglong)
user32.EnumChildWindows.argtypes = (wt.HWND, WNDENUMPROC, wt.LPARAM)
user32.EnumChildWindows.restype = wt.BOOL


def list_child_windows(hwnd):
    found = []

    def _cb(h, _lp):
        found.append(int(h))
        return True

    user32.EnumChildWindows(wt.HWND(hwnd), WNDENUMPROC(_cb), 0)
    return found


class KeySender:

    def __init__(self, vk: int = VK_F, method: str = "scan", hwnd: int = 0):
        self.vk = vk
        self.method = method if method in METHODS else "scan"
        self.hwnd = int(hwnd or 0)
        self.scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFF
        if not self.scan:
            raise RuntimeError("Failed to get the key scan code; please check the runtime environment")
        self._children = None

    def _si(self, use_scan: bool, up: bool) -> None:
        if use_scan:
            flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
            inp = _make_key_input(self.scan, flags)
        else:
            flags = KEYEVENTF_KEYUP if up else 0
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki = KEYBDINPUT(self.vk, 0, flags, 0, 0)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _kbd(self, up: bool) -> None:
        flags = 0x0008 | (0x0002 if up else 0)
        user32.keybd_event(self.vk, self.scan, flags, 0)

    def _post(self, up: bool) -> None:
        msg = WM_KEYUP if up else WM_KEYDOWN
        lp = 1 | (self.scan << 16)
        if up:
            lp |= (1 << 30) | (1 << 31)
        targets = [self.hwnd] if self.hwnd else []
        if self.method == "post_child":
            targets = targets + list_child_windows(self.hwnd) if self.hwnd else []
        for h in targets:
            if h and user32.IsWindow(wt.HWND(h)):
                user32.PostMessageW(wt.HWND(h), msg, self.vk, lp)

    def down(self) -> None:
        m = self.method
        if m == "scan":
            self._si(True, False)
        elif m == "vk":
            self._si(False, False)
        elif m == "keybd":
            self._kbd(False)
        else:
            self._post(False)

    def up(self) -> None:
        m = self.method
        if m == "scan":
            self._si(True, True)
        elif m == "vk":
            self._si(False, True)
        elif m == "keybd":
            self._kbd(True)
        else:
            self._post(True)

    def tap(self, hold_ms: int = 60) -> None:
        self.down()
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        self.up()


def list_windows():
    found = []

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            ln = user32.GetWindowTextLengthW(hwnd)
            if ln > 0:
                buf = ctypes.create_unicode_buffer(ln + 1)
                user32.GetWindowTextW(hwnd, buf, ln + 1)
                if buf.value and buf.value not in SKIP_TITLES:
                    found.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow())


def key_down(vk: int) -> bool:
    return (user32.GetAsyncKeyState(vk) & 0x8000) != 0


HOTKEY_MAP = {"F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78,
              "F10": 0x79, "F11": 0x7A, "F12": 0x7B}


def _build_press_keys():
    keys = {"F%d" % i: 0x6F + i for i in range(1, 13)}      # F1..F12
    keys.update({ch: ord(ch) for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
    keys.update({ch: ord(ch) for ch in "0123456789"})
    keys.update({"Space": 0x20, "Enter": 0x0D, "Tab": 0x09, "Esc": 0x1B})
    return keys


# Keys that can be auto-pressed: name -> virtual-key code. Letters and digits work too,
# they are just not listed in the dropdown to keep the menu short.
PRESS_KEYS = _build_press_keys()
DEFAULT_PRESS_KEY = "F"
DEFAULT_HOTKEY = "F12"

DEFAULTS = {
    "interval_ms": 250,
    "jitter_pct": 25,
    "hold_ms": 60,
    "hold_jitter_pct": 30,
    "start_delay_s": 2.0,
    "target_hwnd": 0,
    "target_title": "",
    "only_foreground": True,
    "hotkey": DEFAULT_HOTKEY,
    "press_key": DEFAULT_PRESS_KEY,
    "method": "scan",
    # Floating status badge: whether it is shown, plus the remembered screen position
    # (-1 means "never dragged, use the default corner")
    "overlay_visible": True,
    "overlay_x": -1,
    "overlay_y": -1,
}

# Window titles used to auto-detect the game. The Chinese entries are the localized
# titles of the official client, so they are data rather than UI text -- do not
# translate them.
TIP_TITLES = ("原神", "云·原神", "云原神", "Genshin", "YuanShen",
              "Genshin Impact", "GenshinImpact")

# Title of the floating badge window. It is a visible window too, so it has to be
# excluded from the "Select target window" list -- otherwise it is easy to bind the
# badge by mistake instead of the game.
OVERLAY_TITLE = "AutoPressF Status Badge"
SKIP_TITLES = (OVERLAY_TITLE,)

CONFIG_NAME = "config.json"
APP_DIR_NAME = "AutoPressF"


def _is_installed(module_dir: str) -> bool:
    """Whether the module lives in an installed location (uvx / uv tool cache env, pip)."""
    p = module_dir.lower().replace("/", "\\")
    return any(k in p for k in ("\\site-packages\\", "\\dist-packages\\",
                                "\\uv\\cache\\", "\\uv\\tools\\"))


def _user_config_dir() -> str:
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            or os.path.expanduser("~"))
    d = os.path.join(base, APP_DIR_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return os.path.expanduser("~")
    return d


def _resolve_config_path() -> str:
    """Decide where the config file lives.

    1. The AUTO_PRESS_F_CONFIG environment variable wins, so several configs can coexist;
    2. Running from a source checkout (python main.py / uv run main.py): keep the config
       in the project directory, matching the original behaviour;
    3. Running installed (uvx / uv tool): the modules sit inside the uv cache, which must
       not be written to. If a config already exists in the launch directory (e.g. uvx
       started from inside a checkout), keep using it so that both ways share the same
       settings; otherwise fall back to %LOCALAPPDATA%\\AutoPressF\\.
    """
    override = os.environ.get("AUTO_PRESS_F_CONFIG")
    if override:
        return os.path.abspath(override)

    module_dir = os.path.dirname(os.path.abspath(__file__))
    if not _is_installed(module_dir):
        return os.path.join(module_dir, CONFIG_NAME)

    cwd_cfg = os.path.join(os.getcwd(), CONFIG_NAME)
    if os.path.exists(cwd_cfg):
        return cwd_cfg
    return os.path.join(_user_config_dir(), CONFIG_NAME)


CONFIG_PATH = _resolve_config_path()


class AutoPresser:
    def __init__(self, on_status=None):
        self.cfg = dict(DEFAULTS)
        self.sender = KeySender(PRESS_KEYS[DEFAULT_PRESS_KEY])
        self._stop = threading.Event()
        self._thread = None
        self.running = False
        self.count = 0
        self.status = "Ready"
        self.on_status = on_status or (lambda _msg: None)

    def load(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.cfg.update({k: v for k, v in json.load(f).items()
                                     if k in DEFAULTS})
            except Exception:
                pass
        return self

    def save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _set_status(self, text):
        self.status = text
        self.on_status(text)

    @staticmethod
    def _jitter(base: float, pct: float) -> float:
        if pct <= 0:
            return base
        delta = base * pct / 100.0
        return max(0.0, random.uniform(base - delta, base + delta))

    def _window_ok(self) -> bool:
        if not self.cfg["only_foreground"]:
            return True
        hwnd = self.cfg["target_hwnd"]
        if not hwnd:
            return True
        if not user32.IsWindow(wt.HWND(hwnd)):
            self._set_status("Target window closed; please reselect")
            return False
        return foreground_hwnd() == hwnd

    def _loop(self):
        cfg = self.cfg
        delay = max(0.0, float(cfg["start_delay_s"]))
        if delay > 0:
            steps = max(1, int(delay * 10))
            for i in range(steps):
                if self._stop.is_set():
                    self.running = False
                    self._set_status("Stopped (total %d presses)" % self.count)
                    return
                self._set_status("Preparing… %.1fs" % ((steps - i) / 10.0))
                time.sleep(0.1)

        while not self._stop.is_set():
            if not self._window_ok():
                self._set_status("Waiting for target window to return to foreground…")
                if self._stop.wait(0.3):
                    break
                continue

            hold = int(round(self._jitter(float(cfg["hold_ms"]),
                                          float(cfg["hold_jitter_pct"]))))
            self.sender.tap(max(5, hold))
            self.count += 1
            self._set_status("Running (%s sent %d times)"
                             % (cfg.get("press_key", DEFAULT_PRESS_KEY),
                                self.count))

            interval = max(0.02, self._jitter(float(cfg["interval_ms"]),
                                              float(cfg["jitter_pct"])) / 1000.0)
            if self._stop.wait(interval):
                break

        self.running = False
        self._set_status("Stopped (total %d presses)" % self.count)

    def press_vk(self) -> int:
        name = self.cfg.get("press_key", DEFAULT_PRESS_KEY)
        return PRESS_KEYS.get(name, PRESS_KEYS[DEFAULT_PRESS_KEY])

    def start(self):
        if self.running:
            return
        self.sender = KeySender(self.press_vk(), self.cfg.get("method", "scan"),
                                self.cfg.get("target_hwnd", 0))
        self.running = True
        self.count = 0
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.running = False

    def toggle(self):
        self.stop() if self.running else self.start()

    def start_hotkey_listener(self):
        def _pump():
            prev = False
            while True:
                vk = HOTKEY_MAP.get(self.cfg["hotkey"],
                                    HOTKEY_MAP[DEFAULT_HOTKEY])
                cur = key_down(vk)
                if cur and not prev:
                    self.toggle()
                prev = cur
                time.sleep(0.03)

        t = threading.Thread(target=_pump, daemon=True)
        t.start()
        return t
