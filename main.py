
import ctypes
import ctypes.wintypes as wt
import datetime
import os
import sys
import tkinter as tk
import traceback

import customtkinter as ctk

from auto_press_f import (CONFIG_PATH, AutoPresser, DEFAULT_HOTKEY,
                          DEFAULT_PRESS_KEY, HOTKEY_MAP, METHODS, OVERLAY_TITLE,
                          PRESS_KEYS, TIP_TITLES, list_windows)

# The log lives next to the config file. The app is a pythonw GUI now (no console), so
# when something goes wrong there is no output anywhere -- this file is the only record.
LOG_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "auto_press_f.log")
LOG_MAX_BYTES = 64 * 1024


def log(msg: str) -> None:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (stamp, msg))
    except OSError:
        pass


# The dropdown only lists function keys and special keys, otherwise the menu gets long
# enough to fall off the screen on high-DPI setups. Letters and digits are valid values
# too -- set press_key directly in the config file.
PRESS_KEY_CHOICES = [k for k in PRESS_KEYS if len(k) > 1 or not k.isalnum()]

# The UI shows the human-readable METHODS description ("SendInput + scancode") while the
# config keeps the internal key ("scan"); map between the two so internal identifiers
# never leak into the interface.
METHOD_BY_LABEL = {label: key for key, label in METHODS.items()}

# ---- palette ----
BG = "#141619"
CARD = "#1c1f24"
EDGE = "#282d34"
FIELD = "#242a31"
FIELD_HI = "#2e343d"
FG = "#e9edf2"
MUTED = "#8b95a4"
DIM = "#606874"
ACCENT = "#4a9eff"
ACCENT_HI = "#6cb2ff"
GREEN = "#3fb950"
RED = "#b8453c"
RED_HI = "#c8524a"

FONT = "Segoe UI"

# The two badge states: (outline, fill, text/dot)
OV_RUN = ("#3fb950", "#12331d", "#7ee787")
OV_IDLE = ("#5a6068", "#23262b", "#8b939e")


def F(size, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def enable_dpi_awareness():
    shcore = ctypes.windll.shcore
    try:
        fn = shcore.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.c_ssize_t]
        fn.restype = ctypes.c_int
        if fn(ctypes.c_ssize_t(-4)):
            return "per-monitor v2"
    except (AttributeError, OSError, ValueError):
        pass
    try:
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_uint]
        if shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor v1"
    except (AttributeError, OSError):
        pass
    try:
        if shcore.SetProcessDpiAwareness(1) == 0:
            return "system"
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "legacy"
    except Exception:
        pass
    return "not applied"


class NumberField(ctk.CTkFrame):
    """Numeric input: -/+ steppers plus direct typing; clamps on blur or Enter."""

    def __init__(self, master, value, step=1, lo=0, hi=9999, decimals=0,
                 on_change=None):
        super().__init__(master, fg_color=FIELD, corner_radius=9, height=34)
        self.pack_propagate(False)
        self.step = step
        self.lo = float(lo)
        self.hi = float(hi)
        self.decimals = decimals
        self.on_change = on_change or (lambda: None)
        self.var = tk.StringVar(value=self._fmt(float(value)))

        btn = dict(width=26, height=26, corner_radius=7, fg_color="transparent",
                   hover_color=FIELD_HI, text_color=MUTED, font=F(14, "bold"))
        ctk.CTkButton(self, text="-", command=lambda: self._bump(-1),
                      **btn).pack(side="left", padx=(3, 0), pady=4)
        self.entry = ctk.CTkEntry(self, textvariable=self.var, height=26,
                                  corner_radius=6, border_width=0,
                                  fg_color=FIELD, text_color=FG,
                                  justify="center", font=F(13), width=44)
        self.entry.pack(side="left", fill="x", expand=True, pady=4)
        ctk.CTkButton(self, text="+", command=lambda: self._bump(1),
                      **btn).pack(side="right", padx=(0, 3), pady=4)

        self.entry.bind("<Return>", lambda _e: self._commit())
        self.entry.bind("<FocusOut>", lambda _e: self._commit())
        self.entry.bind("<Up>", lambda _e: self._bump(1))
        self.entry.bind("<Down>", lambda _e: self._bump(-1))

    def _fmt(self, v):
        if self.decimals:
            return "%.*f" % (self.decimals, v)
        return str(int(round(v)))

    def _bump(self, direction):
        self.set(self.get() + direction * self.step, fire=True)

    def _commit(self):
        self.set(self.get(), fire=True)

    def set(self, value, fire=False):
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = self.lo
        v = max(self.lo, min(self.hi, v))
        self.var.set(self._fmt(v))
        if fire:
            self.on_change()

    def get(self):
        try:
            return float(self.var.get().replace(",", ".").strip())
        except (TypeError, ValueError):
            return self.lo


class WindowPicker:

    def __init__(self, parent, on_pick):
        self.parent = parent
        self.on_pick = on_pick
        self.win = None

    def show(self, current_hwnd=0):
        if self.win is not None:
            try:
                self.win.lift()
                self.win.focus_force()
                return
            except tk.TclError:
                self.win = None

        wins = list_windows()
        top = ctk.CTkToplevel(self.parent)
        top.title("Select target window")
        top.configure(fg_color=BG)
        top.transient(self.parent)
        self.win = top

        ctk.CTkLabel(top, text="Double-click to bind, or select and press OK",
                     font=F(11), text_color=MUTED, anchor="w")\
            .pack(fill="x", padx=16, pady=(14, 8))

        body = ctk.CTkFrame(top, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        # The list sits inside a rounded card with a little padding, otherwise the
        # rounding is invisible (a tk.Listbox is a hard-edged rectangle).
        holder = ctk.CTkFrame(body, fg_color=FIELD, corner_radius=10)
        holder.pack(fill="both", expand=True)
        lb = tk.Listbox(holder, bg=FIELD, fg=FG, selectbackground=ACCENT,
                        selectforeground="#ffffff", activestyle="none",
                        bd=0, highlightthickness=0, height=13,
                        exportselection=False, font=(FONT, 11))
        sb = ctk.CTkScrollbar(holder, command=lb.yview, width=10,
                              fg_color="transparent", button_color=FIELD_HI,
                              button_hover_color="#3a414b")
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", padx=(2, 4), pady=6)

        items = [("(Any window)", 0)] + [(t, h) for h, t in wins]
        for label, _h in items:
            lb.insert("end", label)

        sel = 0
        for i, (_label, h) in enumerate(items):
            if h and h == current_hwnd:
                sel = i
                break
        lb.selection_set(sel)
        lb.see(sel)

        def close():
            top.destroy()
            self.win = None

        def commit(_e=None):
            idx = lb.curselection()
            if not idx:
                return
            _label, hwnd = items[idx[0]]
            title = ""
            if hwnd:
                title = next((t for h, t in wins if h == hwnd), "")
            self.on_pick(hwnd, title)
            close()

        lb.bind("<Double-Button-1>", commit)
        lb.bind("<Return>", commit)
        top.bind("<Escape>", lambda _e: close())

        bar = ctk.CTkFrame(top, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 14))
        bar.columnconfigure(0, weight=1)
        bar.columnconfigure(1, weight=1)
        ctk.CTkButton(bar, text="OK", height=32, corner_radius=9,
                      fg_color=ACCENT, hover_color=ACCENT_HI,
                      text_color="#ffffff", font=F(12, "bold"),
                      command=commit).grid(row=0, column=0, sticky="ew",
                                           padx=(0, 4))
        ctk.CTkButton(bar, text="Cancel", height=32, corner_radius=9,
                      fg_color=FIELD, hover_color=FIELD_HI, text_color=FG,
                      font=F(12), command=close).grid(row=0, column=1,
                                                      sticky="ew", padx=(4, 0))

        lb.focus_force()
        top.update_idletasks()
        top.geometry("520x450")     # CTk logical pixels; it scales them by the DPI factor
        top.resizable(False, False)


class StatusOverlay:
    """Always-on-top badge in a screen corner: "auto-pressing" vs "stopped" at a glance.

    Design notes:
    - A circle plus a transparent color key crops the square window background away, so
      only a small dot remains on screen and barely covers any game UI;
    - The WS_EX_NOACTIVATE extended style means clicking it never steals foreground focus
      from the game, so enabling only_foreground does not stop the pressing when the badge
      is clicked;
    - Drag with the left button to move it (the position is written back to the config),
      single left click toggles, right click opens a menu;
    - Hovering shows the full status text.
    """

    TRANSPARENT_KEY = "#010203"   # color key Windows makes fully transparent
    BASE_DIAM = 38                # base diameter, multiplied by the DPI scale

    def __init__(self, parent, presser, on_toggle, save,
                 on_hide=None, on_show_main=None):
        self.parent = parent
        self.p = presser
        self.cfg = presser.cfg
        self.on_toggle = on_toggle
        self.save = save
        self.on_hide = on_hide or (lambda: None)
        self.on_show_main = on_show_main or (lambda: None)
        self.visible = True
        self._hint = ""
        self._drag = None
        self._moved = False
        self._tip = None
        self._tip_label = None
        self._menu_open = False
        self._hwnd = 0

        self.scale = self._dpi_scale()
        self.d = max(26, int(round(self.BASE_DIAM * self.scale)))

        self.top = tk.Toplevel(parent)
        self.top.title(OVERLAY_TITLE)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=self.TRANSPARENT_KEY)
        try:
            self.top.attributes("-transparentcolor", self.TRANSPARENT_KEY)
            keyed = True
        except tk.TclError:
            # A few environments reject color keys: degrade to a dark square, which is
            # still always-on-top, draggable and clickable
            keyed = False
            self.top.configure(bg=BG)

        d = self.d
        self.cv = tk.Canvas(self.top, width=d, height=d,
                            bg=self.TRANSPARENT_KEY if keyed else BG,
                            highlightthickness=0, bd=0, takefocus=0)
        self.cv.pack()
        self._ring = self.cv.create_oval(1, 1, d - 1, d - 1, width=2,
                                         outline=OV_IDLE[0], fill=OV_IDLE[1])
        self._txt = self.cv.create_text(d / 2, d / 2, text="F", fill=OV_IDLE[2],
                                        font=(FONT,
                                              max(9, int(round(12 * self.scale))),
                                              "bold"))
        r = max(2, int(round(4 * self.scale)))
        off = max(4, int(round(5 * self.scale)))
        self._dot = self.cv.create_oval(d - off - 2 * r, off,
                                        d - off, off + 2 * r,
                                        fill=OV_IDLE[0], outline="")

        for seq, fn in (("<Button-1>", self._on_press),
                        ("<B1-Motion>", self._on_drag),
                        ("<ButtonRelease-1>", self._on_release),
                        ("<Button-3>", self._on_menu),
                        ("<Enter>", self._on_enter),
                        ("<Leave>", self._on_leave)):
            self.cv.bind(seq, fn)

        self.top.update_idletasks()
        self._place(self.cfg.get("overlay_x", -1), self.cfg.get("overlay_y", -1))
        # The extended styles can only be applied once the window is actually on screen,
        # otherwise the outermost wrapper handle is not available yet
        self._no_activate()

    def _dpi_scale(self):
        try:
            return max(1.0, float(self.parent.winfo_fpixels("1i")) / 96.0)
        except Exception:
            return 1.0

    def _no_activate(self):
        """Add WS_EX_NOACTIVATE / WS_EX_TOOLWINDOW: no foreground stealing, no Alt-Tab.

        Tk's winfo_id() is only the inner window; what is actually drawn on screen is the
        wrapper above it, so the flags have to be applied along the whole GetParent chain.
        """
        gwl_exstyle, noactivate, toolwindow = -20, 0x08000000, 0x00000080
        u32 = ctypes.windll.user32
        try:
            get = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
            put = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
            get.argtypes = [wt.HWND, ctypes.c_int]
            get.restype = ctypes.c_ssize_t
            put.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
            put.restype = ctypes.c_ssize_t
            u32.GetParent.argtypes = [wt.HWND]
            u32.GetParent.restype = wt.HWND
            h = int(self.top.winfo_id())
            last = h
            for _ in range(4):
                if not h:
                    break
                ex = get(wt.HWND(h), gwl_exstyle)
                put(wt.HWND(h), gwl_exstyle, ex | noactivate | toolwindow)
                last = h
                h = int(u32.GetParent(wt.HWND(h)) or 0)
            # Remember the outermost handle (the one really on screen) for topmost checks
            self._hwnd = last
        except Exception:
            pass

    def _topmost_ok(self) -> bool:
        if not self._hwnd:
            return True
        try:
            u32 = ctypes.windll.user32
            u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            u32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
            return bool(u32.GetWindowLongPtrW(wt.HWND(self._hwnd), -20)
                        & 0x00000008)      # WS_EX_TOPMOST
        except Exception:
            return True

    def _ensure_topmost(self):
        """Re-assert topmost only when another topmost window really covers us, so that
        repeated SetWindowPos calls do not interfere with the right-click menu."""
        if self._menu_open or self._topmost_ok():
            return
        try:
            self.top.attributes("-topmost", True)
        except tk.TclError:
            pass

    def _place(self, x, y):
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            x = y = -1
        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        if x < 0 or y < 0 or x > sw - self.d or y > sh - self.d:
            # Default to the top-right corner: away from the minimap / health bar area
            x = sw - self.d - max(8, int(round(24 * self.scale)))
            y = max(8, int(round(72 * self.scale)))
        self._x, self._y = x, y
        self._sync_geometry()

    def _sync_geometry(self):
        self.top.geometry("%dx%d+%d+%d" % (self.d, self.d, self._x, self._y))

    def _clamp(self):
        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        self._x = max(0, min(self._x, sw - self.d))
        self._y = max(0, min(self._y, sh - self.d))

    def refresh(self, running, hint=""):
        outline, fill, text = OV_RUN if running else OV_IDLE
        try:
            self.cv.itemconfigure(self._ring, outline=outline, fill=fill)
            self.cv.itemconfigure(self._txt, fill=text)
            self.cv.itemconfigure(self._dot, fill=outline)
            # Only re-assert topmost when covered by another topmost window
            self._ensure_topmost()
        except tk.TclError:
            return
        self._hint = hint or ("Auto-press F: running" if running
                              else "Auto-press F: stopped")
        if self._tip is not None:
            try:
                self._tip_label.configure(text=self._hint)
            except tk.TclError:
                pass

    def _on_press(self, e):
        self._drag = (e.x_root, e.y_root, self._x, self._y)
        self._moved = False

    def _on_drag(self, e):
        if not self._drag:
            return
        sx, sy, wx, wy = self._drag
        dx, dy = e.x_root - sx, e.y_root - sy
        if abs(dx) > 3 or abs(dy) > 3:
            self._moved = True
        self._x, self._y = wx + dx, wy + dy
        self._sync_geometry()

    def _on_release(self, _e):
        if self._drag is None:
            return
        self._drag = None
        if self._moved:
            self._clamp()
            self._sync_geometry()
            self.cfg["overlay_x"], self.cfg["overlay_y"] = self._x, self._y
            self.save()
        else:
            self.on_toggle()

    def _on_menu(self, e):
        m = tk.Menu(self.parent, tearoff=0, bg=CARD, fg=FG, bd=0,
                    activebackground=ACCENT, activeforeground="#ffffff",
                    relief="flat")
        m.add_command(label="Stop auto-press" if self.p.running
                      else "Start auto-press", command=self.on_toggle)
        m.add_command(label="Show main window", command=self.on_show_main)
        m.add_separator()
        m.add_command(label="Hide this badge", command=self.hide)
        self._menu_open = True
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu_open = False
            m.grab_release()

    def _on_enter(self, _e):
        self._show_tip()

    def _on_leave(self, _e):
        self._hide_tip()

    def _show_tip(self):
        if not self.visible:
            return
        if self._tip is None:
            self._tip = tk.Toplevel(self.top)
            self._tip.overrideredirect(True)
            self._tip.attributes("-topmost", True)
            self._tip.configure(bg=CARD)
            self._tip_label = tk.Label(
                self._tip, text="", bg=CARD, fg=FG, padx=8, pady=4,
                justify="left", anchor="w",
                font=(FONT, max(8, int(round(9 * self.scale)))))
            self._tip_label.pack()
        self._tip_label.configure(text=self._hint + "\nclick: start/stop · drag: move")
        self._tip.update_idletasks()
        w = self._tip.winfo_reqwidth()
        sw = self._tip.winfo_screenwidth()
        x = max(4, min(self._x + self.d - w, sw - w - 4))
        try:
            self._tip.geometry("+%d+%d" % (int(x), int(self._y + self.d + 6)))
            self._tip.deiconify()
            self._tip.lift()
        except tk.TclError:
            pass

    def _hide_tip(self):
        if self._tip is None:
            return
        try:
            self._tip.withdraw()
        except tk.TclError:
            pass

    def hide(self):
        self._hide_tip()
        self.visible = False
        try:
            self.top.withdraw()
        except tk.TclError:
            return
        self.cfg["overlay_visible"] = False
        self.save()
        self.on_hide()

    def show(self):
        self.visible = True
        try:
            self.top.deiconify()
            self._sync_geometry()
            self.top.attributes("-topmost", True)
            self._no_activate()
        except tk.TclError:
            return
        self.cfg["overlay_visible"] = True
        self.save()

    def destroy(self):
        self._hide_tip()
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class App:
    def __init__(self, root):
        self.root = root
        self.p = AutoPresser(on_status=self.set_status).load()
        self.p.start_hotkey_listener()

        root.title("F-Key Auto Presser")
        root.configure(fg_color=BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        # Note: do NOT call resizable(False, False) here -- it locks min/max to the
        # *current* size, and at this point the content has not been built yet, so the
        # window would be frozen at the wrong size.

        self.only_fg = tk.BooleanVar()
        self.hotkey = tk.StringVar()
        self.press_key = tk.StringVar()
        self.method = tk.StringVar()
        self.win_var = tk.StringVar()
        self.status = tk.StringVar(value="Ready")
        self.badge_on = tk.BooleanVar(
            value=bool(self.p.cfg.get("overlay_visible", True)))

        # Real DPI scale (96 dpi = 1.0). Plain tk.Label wraplength and pixel font sizes
        # are computed from it; CTk's internal logical-pixel scaling must not be used here.
        try:
            self._scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
        except Exception:
            self._scale = 1.0

        self.picker = WindowPicker(root, self.on_window_pick)
        self._build()
        self.sync_from_cfg()

        # Floating badge: a separate small top-level window, still owned by the main
        # window's lifecycle even when the main window is hidden
        self.overlay = StatusOverlay(root, self.p, on_toggle=self.toggle,
                                     save=self.p.save,
                                     on_hide=lambda: self.badge_on.set(False),
                                     on_show_main=self.show_main)
        if not self.badge_on.get():
            self.overlay.hide()

        self._apply_size()
        log("window actual=%dx%d req=%dx%d scale=%.2f"
            % (root.winfo_width(), root.winfo_height(),
               root.winfo_reqwidth(), root.winfo_reqheight(), self._scale))
        root.after(150, self.auto_bind_game)
        root.after(250, self.poll_state)

    # ---------- UI ----------
    def _card(self, title):
        c = ctk.CTkFrame(self.root, fg_color=CARD, corner_radius=14,
                         border_width=1, border_color=EDGE)
        c.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(c, text=title.upper(), font=F(10, "bold"),
                     text_color=DIM, anchor="w")\
            .pack(fill="x", padx=16, pady=(11, 2))
        return c

    def _grid(self, parent, uniform, cols=3):
        g = ctk.CTkFrame(parent, fg_color="transparent")
        g.pack(fill="x", padx=14, pady=(2, 12))
        for i in range(cols):
            g.columnconfigure(i, weight=1, uniform=uniform)
        return g

    @staticmethod
    def _cell(grid, col, row, text, span=1):
        wrap = ctk.CTkFrame(grid, fg_color="transparent")
        wrap.grid(row=row, column=col, columnspan=span, sticky="ew",
                  padx=(0 if col == 0 else 10, 0), pady=(0, 8))
        ctk.CTkLabel(wrap, text=text, font=F(11), text_color=MUTED,
                     anchor="w").pack(fill="x", pady=(0, 4))
        return wrap

    def _build(self):
        head = ctk.CTkFrame(self.root, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 14))
        box = ctk.CTkFrame(head, fg_color="transparent")
        box.pack(side="left")
        ctk.CTkLabel(box, text="F-Key Auto Presser", font=F(16, "bold"),
                     text_color=FG, anchor="w").pack(anchor="w")
        ctk.CTkLabel(box, text="Story-skip helper", font=F(11),
                     text_color=MUTED, anchor="w").pack(anchor="w")

        self.pill = ctk.CTkFrame(head, fg_color=FIELD, corner_radius=11,
                                 height=24)
        self.pill.pack(side="right", pady=(3, 0))
        self.pill_dot = ctk.CTkLabel(self.pill, text="●", font=F(9),
                                     text_color=DIM, width=9)
        self.pill_dot.pack(side="left", padx=(10, 0), pady=3)
        self.pill_text = ctk.CTkLabel(self.pill, text="Idle",
                                      font=F(11, "bold"), text_color=MUTED)
        self.pill_text.pack(side="left", padx=(3, 11), pady=3)

        c = self._card("Target window")
        # Fixed width + pack_propagate(False): a long window title would otherwise widen
        # the whole window and clip everything on the right. The title itself is also
        # truncated (see _fmt).
        holder = ctk.CTkFrame(c, fg_color=FIELD, corner_radius=9, height=36,
                              width=500)
        holder.pack(fill="x", padx=14, pady=(4, 8))
        holder.pack_propagate(False)
        ctk.CTkLabel(holder, textvariable=self.win_var, font=F(12),
                     text_color=FG, anchor="w")\
            .pack(side="left", fill="y", padx=11)

        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=14)
        row.columnconfigure(0, weight=1, uniform="b")
        row.columnconfigure(1, weight=1, uniform="b")
        secondary = dict(height=32, corner_radius=9, fg_color=FIELD,
                         hover_color=FIELD_HI, text_color=FG, font=F(12))
        ctk.CTkButton(row, text="Select window", command=self.open_picker,
                      **secondary).grid(row=0, column=0, sticky="ew",
                                        padx=(0, 4))
        ctk.CTkButton(row, text="Any window", command=self.clear_window,
                      **secondary).grid(row=0, column=1, sticky="ew",
                                        padx=(4, 0))

        switch = dict(font=F(12), text_color=FG, progress_color=ACCENT,
                      switch_width=36, switch_height=20,
                      button_color="#f2f5f9", button_hover_color="#ffffff")
        sw = ctk.CTkFrame(c, fg_color="transparent")
        sw.pack(fill="x", padx=14, pady=(12, 13))
        sw.columnconfigure(0, weight=1, uniform="s")
        sw.columnconfigure(1, weight=1, uniform="s")
        ctk.CTkSwitch(sw, text="Foreground only", variable=self.only_fg,
                      command=self.push_cfg, **switch)\
            .grid(row=0, column=0, sticky="w")
        ctk.CTkSwitch(sw, text="Floating badge", variable=self.badge_on,
                      command=self.toggle_badge, **switch)\
            .grid(row=0, column=1, sticky="w")

        c = self._card("Timing")
        # Two columns, not three: a single number field (- value +) already needs about
        # 220 logical pixels, so three of them would push the card past the window width
        # and clip the right edge.
        g = self._grid(c, "t", cols=2)
        self.interval = NumberField(
            self._cell(g, 0, 0, "Interval (ms)"), 250, step=10, lo=40,
            hi=5000, on_change=self.push_cfg)
        self.interval.pack(fill="x")
        self.jitter = NumberField(
            self._cell(g, 1, 0, "Jitter (%)"), 25, step=5, lo=0, hi=100,
            on_change=self.push_cfg)
        self.jitter.pack(fill="x")
        self.hold = NumberField(
            self._cell(g, 0, 1, "Hold (ms)"), 60, step=5, lo=5, hi=500,
            on_change=self.push_cfg)
        self.hold.pack(fill="x")
        self.hold_jitter = NumberField(
            self._cell(g, 1, 1, "Hold jitter (%)"), 30, step=5, lo=0,
            hi=100, on_change=self.push_cfg)
        self.hold_jitter.pack(fill="x")
        self.start_delay = NumberField(
            self._cell(g, 0, 2, "Start delay (s)"), 2.0, step=0.5, lo=0,
            hi=10, decimals=1, on_change=self.push_cfg)
        self.start_delay.pack(fill="x")

        c = self._card("Keys")
        g = self._grid(c, "k", cols=2)
        om = dict(height=34, corner_radius=9, fg_color=FIELD,
                  button_color=FIELD, button_hover_color=FIELD_HI,
                  text_color=FG, dropdown_fg_color=CARD,
                  dropdown_hover_color=FIELD_HI, dropdown_text_color=FG,
                  font=F(12), dropdown_font=F(12),
                  command=lambda _v: self.push_cfg())
        ctk.CTkOptionMenu(self._cell(g, 0, 0, "Toggle hotkey"),
                          values=list(HOTKEY_MAP.keys()),
                          variable=self.hotkey, **om).pack(fill="x")
        ctk.CTkOptionMenu(self._cell(g, 1, 0, "Press key"),
                          values=PRESS_KEY_CHOICES,
                          variable=self.press_key, **om).pack(fill="x")

        # On its own row so it lines up with the card padding (a cell spanning two grid
        # columns ends up slightly narrower than the fields above it).
        dg = ctk.CTkFrame(c, fg_color="transparent")
        dg.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(dg, text="Delivery method", font=F(11), text_color=MUTED,
                     anchor="w").pack(fill="x", pady=(0, 4))
        ctk.CTkOptionMenu(dg, values=list(METHODS.values()),
                          variable=self.method, **om).pack(fill="x")

        self.btn = ctk.CTkButton(self.root, text="Start", height=44,
                                 corner_radius=11, fg_color=ACCENT,
                                 hover_color=ACCENT_HI, text_color="#ffffff",
                                 font=F(14, "bold"), command=self.toggle)
        self.btn.pack(fill="x", padx=18, pady=(4, 10))

        ctk.CTkLabel(self.root, textvariable=self.status, font=F(11),
                     text_color=MUTED, anchor="w")\
            .pack(fill="x", padx=20)

        # A plain tk.Label instead of CTkLabel: CTkLabel mixes its own scaling into
        # wraplength and still requested the full sentence width (it once stretched the
        # window to 1300 px). Here wraplength is physical pixels and the font size is
        # negative, i.e. pixel height, so neither depends on tk scaling.
        tip_font = (FONT, -max(11, int(round(10.5 * self._scale))))
        self.tip = tk.Label(
            self.root, bg=BG, fg=MUTED, anchor="w", justify="left",
            font=tip_font, wraplength=int(round(512 * self._scale)),
            text="Keep the interval at 150 ms or more and leave some jitter on. "
                 "If the game runs as administrator, this tool must too — "
                 "otherwise Windows drops its input silently.")
        self.tip.pack(fill="x", padx=20, pady=(7, 18))

    def _apply_size(self):
        """Let the window take its natural content size.

        Do not compute the size by hand: CTk's geometry() applies its own DPI scaling and
        is additionally clamped by the min/max values that resizable(False, False) sets,
        so hand-computed numbers easily disagree with reality (the result is a clipped
        right edge or a window that is too small). All that is needed here: give the hint
        text a DPI-scaled wrap width, then clear CTk's default geometry with the native
        wm_geometry("") so Tk lays the window out at its requested size, and finally lock
        it against resizing.
        """
        try:
            self.tip.configure(wraplength=int(round(512 * self._scale)))
        except tk.TclError:
            pass
        self.root.update_idletasks()
        self.root.wm_geometry("")
        self.root.update_idletasks()
        self.root.resizable(False, False)

    @staticmethod
    def _fmt(hwnd, title):
        # Game / Explorer titles can be long: truncate before putting them in a fixed box
        t = (title or "").strip()
        if len(t) > 26:
            t = t[:25] + "…"
        return "%s   [0x%X]" % (t, hwnd) if t else "[0x%X]" % hwnd

    # ---------- behaviour ----------
    def open_picker(self):
        self.picker.show(self.p.cfg.get("target_hwnd", 0))

    def auto_bind_game(self):
        wins = list_windows()
        saved = self.p.cfg.get("target_hwnd", 0)
        for h, t in wins:
            if saved and h == saved:
                self.p.cfg["target_title"] = t
                self.win_var.set(self._fmt(h, t))
                return
        for h, t in wins:
            if any(k.lower() in t.lower() for k in TIP_TITLES):
                self.on_window_pick(h, t)
                self.set_status("Auto-bound to %s" % t)
                return

    def on_window_pick(self, hwnd, title):
        self.p.cfg["target_hwnd"] = int(hwnd)
        self.p.cfg["target_title"] = title
        self.win_var.set(self._fmt(hwnd, title) if hwnd else "(Any window)")
        if hwnd:
            self.only_fg.set(True)
        self.push_cfg()

    def clear_window(self):
        self.on_window_pick(0, "")

    def sync_from_cfg(self):
        c = self.p.cfg
        self.interval.set(c["interval_ms"])
        self.jitter.set(c["jitter_pct"])
        self.hold.set(c["hold_ms"])
        self.hold_jitter.set(c["hold_jitter_pct"])
        self.start_delay.set(float(c["start_delay_s"]))
        self.only_fg.set(bool(c["only_foreground"]))
        self.hotkey.set(c["hotkey"] if c["hotkey"] in HOTKEY_MAP
                        else DEFAULT_HOTKEY)
        self.press_key.set(c.get("press_key") if c.get("press_key") in PRESS_KEYS
                           else DEFAULT_PRESS_KEY)
        self.method.set(METHODS[c["method"]] if c.get("method") in METHODS
                        else METHODS["scan"])
        self.win_var.set(self._fmt(c["target_hwnd"], c["target_title"])
                         if c["target_hwnd"] else "(Any window)")

    def push_cfg(self, *_):
        c = self.p.cfg
        c["interval_ms"] = int(round(max(40.0, min(5000.0, self.interval.get()))))
        c["jitter_pct"] = int(round(max(0.0, min(100.0, self.jitter.get()))))
        c["hold_ms"] = int(round(max(5.0, min(500.0, self.hold.get()))))
        c["hold_jitter_pct"] = int(round(max(0.0, min(100.0,
                                                      self.hold_jitter.get()))))
        c["start_delay_s"] = float(max(0.0, min(10.0, self.start_delay.get())))
        c["only_foreground"] = bool(self.only_fg.get())
        c["hotkey"] = self.hotkey.get() if self.hotkey.get() in HOTKEY_MAP \
            else DEFAULT_HOTKEY
        _k = self.press_key.get()
        c["press_key"] = _k if _k in PRESS_KEYS else DEFAULT_PRESS_KEY
        _m = METHOD_BY_LABEL.get(self.method.get(), "scan")
        c["method"] = _m
        self.method.set(METHODS[_m])
        self.press_key.set(c["press_key"])
        self.p.save()

    def set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    def poll_state(self):
        key = self.p.cfg.get("press_key", DEFAULT_PRESS_KEY)
        hot = self.p.cfg["hotkey"]
        if self.p.running:
            self.btn.configure(text="Stop  ·  %s" % hot, fg_color=RED,
                               hover_color=RED_HI)
            self.pill_dot.configure(text_color=GREEN)
            self.pill_text.configure(text="Running", text_color=GREEN)
        else:
            self.btn.configure(text="Start  ·  %s" % hot, fg_color=ACCENT,
                               hover_color=ACCENT_HI)
            self.pill_dot.configure(text_color=DIM)
            self.pill_text.configure(text="Idle", text_color=MUTED)
        # Badge and button share the same state: green dot = auto-pressing, gray = stopped
        self.overlay.refresh(self.p.running,
                             "Auto-press %s: %s" % (key, self.p.status))
        self.root.after(300, self.poll_state)

    def toggle_badge(self):
        if self.badge_on.get():
            self.overlay.show()
        else:
            self.overlay.hide()

    def show_main(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def toggle(self):
        self.push_cfg()
        if self.p.running:
            self.p.stop()
            self.set_status("Stopped · %d presses sent" % self.p.count)
        elif self.p.cfg["press_key"] == self.p.cfg["hotkey"]:
            # Otherwise the auto-pressed key would trigger its own toggle hotkey and
            # flip the state back and forth
            self.set_status("Press key and hotkey must be different keys")
        else:
            self.p.start()

    def on_close(self):
        self.p.stop()
        self.push_cfg()
        self.overlay.destroy()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    log("---- start pid=%d" % os.getpid())
    log("cwd=%s" % os.getcwd())
    log("argv=%s" % (sys.argv,))
    log("exe=%s" % sys.executable)
    try:
        import elevate
        log("admin=%s" % elevate.is_admin())
        if "--no-elevate" in sys.argv[1:]:
            log("elevation skipped (--no-elevate)")
        else:
            elevate.ensure_admin()
        log("elevation done")
        log("dpi=%s" % enable_dpi_awareness())
        ctk.set_appearance_mode("dark")
        root = ctk.CTk(fg_color=BG)
        log("tk root created")
        App(root)
        log("ui built, entering mainloop")
        root.mainloop()
        log("mainloop exited cleanly")
    except BaseException:
        log("CRASH\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
