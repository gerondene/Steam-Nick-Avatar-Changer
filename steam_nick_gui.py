#!/usr/bin/env python3
"""Окно для смены ника в Steam — со сменой оформления на ходу."""
import contextlib
import io
import json
import os
import queue
import sys
import threading
from pathlib import Path
from tkinter import filedialog

sys.path.insert(0, str(Path(__file__).parent))
import steam_nick as core  # noqa: E402

try:
    import customtkinter as ctk
except ImportError:
    sys.exit("Нужен customtkinter:  pip install customtkinter==5.2.2")

THEMES = {
    "Standard": dict(mode="dark", bg="#12161d", card="#1b2230", field="#232c3d",
                     accent="#4aa8e0", accent_h="#3a8dbf", on_accent="#0b1016",
                     text="#e6edf5", muted="#8b97a8", good="#67d391", bad="#f0736a",
                     danger="#5a2b2b", r=14, border=0, border_c="#232c3d", font="Segoe UI", tab_sel="#3a8dbf"),
    "Legacy": dict(mode="light", bg="#f0f0f0", card="#f0f0f0", field="#ffffff",
                   accent="#e1e1e1", accent_h="#cde8fa", on_accent="#000000",
                   text="#000000", muted="#4a4a4a", good="#0a6b2a", bad="#a80000",
                   danger="#f0c0c0", r=2, border=1, border_c="#9a9a9a", font="Segoe UI", tab_sel="#cde8fa"),
    "Steam": dict(mode="dark", bg="#171a21", card="#1b2838", field="#2a475e",
                  accent="#66c0f4", accent_h="#4b93b8", on_accent="#0d1117",
                  text="#c7d5e0", muted="#7a8b99", good="#a4d007", bad="#e05a4f",
                  danger="#5a2b2b", r=6, border=0, border_c="#2a475e", font="Segoe UI", tab_sel="#4b93b8"),
    "Midnight": dict(mode="dark", bg="#000000", card="#0b0b10", field="#15151f",
                     accent="#8b7bf7", accent_h="#6f5fe0", on_accent="#0b0b10",
                     text="#f2f2f7", muted="#7d7d8a", good="#5ee6a0", bad="#ff6b6b",
                     danger="#3a1520", r=18, border=0, border_c="#15151f", font="Segoe UI", tab_sel="#6f5fe0"),
    "Light": dict(mode="light", bg="#f6f8fb", card="#ffffff", field="#eef2f7",
                  accent="#2f7fd1", accent_h="#255f9e", on_accent="#ffffff",
                  text="#1a2230", muted="#6b7684", good="#0f7a3d", bad="#c0392b",
                  danger="#f2d0cc", r=14, border=0, border_c="#dde4ec", font="Segoe UI", tab_sel="#dce9f6"),
    "Terminal": dict(mode="dark", bg="#050805", card="#0a100a", field="#0f1a0f",
                     accent="#33ff66", accent_h="#22cc4d", on_accent="#03110a",
                     text="#8bff9e", muted="#3f7a4a", good="#33ff66", bad="#ff5555",
                     danger="#3a1010", r=0, border=1, border_c="#1d3a22", font="Consolas", tab_sel="#1a3a22"),
    # Палитра снята пипеткой со скриншота: фон #1c1c1c, панели #232323,
    # текст #dcdcdc, акцент #ff4f5e (hue 355).
    "Fatality": dict(mode="dark", bg="#141414", card="#1c1c1c", field="#232323",
                     accent="#ff4f5e", accent_h="#d93f4d", on_accent="#1a0d0f",
                     text="#dcdcdc", muted="#707070", good="#79c46b", bad="#ff4f5e",
                     danger="#4a1f24", r=4, border=1, border_c="#262626", font="Segoe UI", tab_sel="#d93f4d"),
}
DEFAULT_THEME = "Standard"

CORE_LOCK = threading.Lock()


def run_core(fn):
    """Вызвать функцию ядра, собрав её print-ы. -> (результат, текст)

    redirect_stdout подменяет поток на весь процесс, поэтому задачи
    выполняем по одной — иначе перекрывающиеся вызовы вернут sys.stdout
    в чужой буфер."""
    buf = io.StringIO()
    with CORE_LOCK:
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                result = fn()
            return result, buf.getvalue().strip()
        except SystemExit as e:
            code = e.code if isinstance(e.code, str) else buf.getvalue().strip()
            return None, code or "Не вышло"
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"


def read_cfg() -> dict:
    """Читаем конфиг мягко: без токена или с битым JSON окно всё равно откроется,
    чтобы токен можно было вставить прямо в интерфейсе."""
    cfg = {}
    if core.CONFIG.exists():
        with contextlib.suppress(json.JSONDecodeError):
            cfg = json.loads(core.CONFIG.read_text("utf-8"))
    cfg.setdefault("steam_login_secure", "")
    cfg.setdefault("presets", [])
    if cfg.get("theme") not in THEMES:
        cfg["theme"] = DEFAULT_THEME
    return cfg

class App(ctk.CTk):
    def __init__(self):
        self.cfg = read_cfg()
        self.t = THEMES[self.cfg["theme"]]
        ctk.set_appearance_mode(self.t["mode"])
        super().__init__(fg_color=self.t["bg"])
        self.title("Steam ник")
        self.geometry("470x700")
        self.minsize(430, 580)
        self.jobs: queue.Queue = queue.Queue()
        self.session = None
        self.steamid = self.sid = self.avatar_link = ""
        self.rows: list = []
        self.abtns: list = []
        self.thumbs: list = []
        self.pic_img = None
        self.build()
        self.connect()
        self.after(80, self._drain)

    # ---------- кирпичики оформления ----------
    def font(self, size: int = 12, bold: bool = False) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.t["font"], size=size,
                           weight="bold" if bold else "normal")

    def card(self, row: int, grow: bool = False) -> ctk.CTkFrame:
        c = ctk.CTkFrame(self, corner_radius=self.t["r"], fg_color=self.t["card"],
                         border_width=self.t["border"], border_color=self.t["border_c"])
        c.grid(row=row, column=0, sticky="nsew" if grow else "ew", padx=14, pady=7)
        c.grid_columnconfigure(0, weight=1)
        return c

    def cap(self, parent, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, text_color=self.t["muted"],
                            font=self.font(11, bold=True))

    def btn(self, parent, text: str, cmd, primary: bool = False, **kw) -> ctk.CTkButton:
        t = self.t
        return ctk.CTkButton(parent, text=text, command=cmd, corner_radius=t["r"],
                             fg_color=t["accent"] if primary else t["field"],
                             hover_color=t["accent_h"],
                             text_color=t["on_accent"] if primary else t["text"],
                             border_width=t["border"], border_color=t["border_c"],
                             font=self.font(12, bold=primary), **kw)

    def field(self, parent, **kw) -> ctk.CTkEntry:
        t = self.t
        return ctk.CTkEntry(parent, height=38, corner_radius=t["r"], fg_color=t["field"],
                            border_width=t["border"], border_color=t["border_c"],
                            text_color=t["text"], font=self.font(12), **kw)

    # ---------- разметка ----------
    def build(self, keep_nick: str = "", tab: str = "Ник") -> None:
        for w in self.winfo_children():
            w.destroy()
        self.rows, self.abtns, self.thumbs = [], [], []
        self.configure(fg_color=self.t["bg"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._head()
        self._tabs(tab)
        self._footer()
        if keep_nick:
            self.entry.insert(0, keep_nick)
            self._count()
        self.fill()
        self.fill_avatars()
        self.show_preview()

    def _head(self) -> None:
        c = self.card(0)
        c.grid_columnconfigure(0, weight=0)
        c.grid_columnconfigure(1, weight=1)
        self.pic = ctk.CTkLabel(c, text="?", width=54, height=54, fg_color=self.t["field"],
                                text_color=self.t["muted"], font=self.font(18),
                                corner_radius=max(self.t["r"] - 4, 0))
        self.pic.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=13)
        self.cap(c, "ТЕКУЩИЙ НИК").grid(row=0, column=1, sticky="sw", pady=(14, 0))
        self.now = ctk.CTkLabel(c, text="…", text_color=self.t["text"], anchor="w",
                                font=self.font(19, bold=True))
        self.now.grid(row=1, column=1, sticky="nw", pady=(0, 14))
        self.b_refresh = self.btn(c, "⟳", self.connect, width=40, height=40)
        self.b_refresh.configure(font=self.font(17))
        self.b_refresh.grid(row=0, column=2, rowspan=2, padx=(8, 14))

    def _tabs(self, active: str) -> None:
        t = self.t
        self.tabs = ctk.CTkTabview(
            self, corner_radius=t["r"], fg_color=t["card"],
            border_width=t["border"], border_color=t["border_c"],
            segmented_button_fg_color=t["field"],
            segmented_button_selected_color=t["tab_sel"],
            segmented_button_selected_hover_color=t["tab_sel"],
            segmented_button_unselected_color=t["field"],
            segmented_button_unselected_hover_color=t["accent_h"],
            text_color=t["text"], anchor="n")
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=14, pady=7)
        for name in ("Ник", "Аватар", "Токен"):
            self.tabs.add(name)
            self.tabs.tab(name).grid_columnconfigure(0, weight=1)
        self.tabs.set(active if active in ("Ник", "Аватар", "Токен") else "Ник")
        self._tab_nick(self.tabs.tab("Ник"))
        self._tab_avatar(self.tabs.tab("Аватар"))
        self._tab_token(self.tabs.tab("Токен"))

    def _tab_nick(self, p) -> None:
        p.grid_rowconfigure(1, weight=1)
        self.cap(p, "ПРЕСЕТЫ").grid(row=0, column=0, sticky="w", padx=6, pady=(6, 4))
        self.box = ctk.CTkScrollableFrame(p, fg_color="transparent", corner_radius=0,
                                         scrollbar_button_color=self.t["field"],
                                         scrollbar_button_hover_color=self.t["accent_h"])
        self.box.grid(row=1, column=0, sticky="nsew")
        self.box.grid_columnconfigure(0, weight=1)
        self.b_cycle = self.btn(p, "Следующий по кругу", self.cycle, height=36)
        self.b_cycle.grid(row=2, column=0, sticky="ew", padx=6, pady=(8, 10))

        self.cap(p, "СВОЙ НИК").grid(row=3, column=0, sticky="w", padx=6, pady=(2, 4))
        line = ctk.CTkFrame(p, fg_color="transparent")
        line.grid(row=4, column=0, sticky="ew", padx=6)
        line.grid_columnconfigure(0, weight=1)
        self.entry = self.field(line, placeholder_text="впиши ник и нажми Enter")
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _: self.change(self.entry.get().strip()))
        self.entry.bind("<KeyRelease>", self._count)
        self._hotkeys(self.entry)
        self.count = ctk.CTkLabel(line, text="0/32", width=44, text_color=self.t["muted"],
                                  font=self.font(11))
        self.count.grid(row=0, column=1, padx=(6, 0))
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.grid(row=5, column=0, sticky="ew", padx=6, pady=(8, 10))
        row.grid_columnconfigure((0, 1), weight=1)
        self.b_set = self.btn(row, "Поставить",
                              lambda: self.change(self.entry.get().strip()),
                              primary=True, height=36)
        self.b_set.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.b_add = self.btn(row, "В пресеты", self.add_preset, height=36)
        self.b_add.grid(row=0, column=1, sticky="ew", padx=(4, 0))

    def _tab_avatar(self, p) -> None:
        p.grid_rowconfigure(1, weight=1)
        self.cap(p, f"КАРТИНКИ ИЗ ПАПКИ {core.AVATARS.name.upper()}").grid(
            row=0, column=0, sticky="w", padx=6, pady=(6, 4))
        self.abox = ctk.CTkScrollableFrame(p, fg_color="transparent", corner_radius=0,
                                          scrollbar_button_color=self.t["field"],
                                          scrollbar_button_hover_color=self.t["accent_h"])
        self.abox.grid(row=1, column=0, sticky="nsew")
        self.abox.grid_columnconfigure((0, 1, 2), weight=1)
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=6, pady=(8, 6))
        row.grid_columnconfigure(0, weight=1)
        self.b_pick = self.btn(row, "Выбрать файл…", self.choose_file, primary=True, height=36)
        self.b_pick.grid(row=0, column=0, sticky="ew")
        self.b_folder = self.btn(row, "Папка", self.open_folder, width=70, height=36)
        self.b_folder.grid(row=0, column=1, padx=(6, 0))
        self.b_rescan = self.btn(row, "⟳", self.fill_avatars, width=40, height=36)
        self.b_rescan.grid(row=0, column=2, padx=(6, 0))
        ctk.CTkLabel(p, text="jpg, png или gif до 1 МБ. Большие сожму сам, "
                            "гифки нужно уложить в лимит заранее.",
                     text_color=self.t["muted"], anchor="w", font=self.font(10),
                     wraplength=380, justify="left").grid(row=3, column=0, sticky="ew",
                                                          padx=6, pady=(0, 10))

    def _tab_token(self, p) -> None:
        t = self.t
        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        head.grid_columnconfigure(0, weight=1)
        self.cap(head, "steamLoginSecure").grid(row=0, column=0, sticky="w")
        self.eye = ctk.CTkCheckBox(head, text="показать", width=20, checkbox_width=17,
                                   checkbox_height=17, corner_radius=max(t["r"] // 3, 0),
                                   border_width=2, fg_color=t["accent"],
                                   hover_color=t["accent_h"], text_color=t["muted"],
                                   border_color=t["muted"], font=self.font(11),
                                   command=self._toggle_eye)
        self.eye.grid(row=0, column=1, sticky="e")
        line = ctk.CTkFrame(p, fg_color="transparent")
        line.grid(row=1, column=0, sticky="ew", padx=6)
        line.grid_columnconfigure(0, weight=1)
        self.token = self.field(line, show="•", placeholder_text="76561198…%7C%7CeyJ0eXAi…")
        self.token.grid(row=0, column=0, sticky="ew")
        self.token.insert(0, self.cfg.get("steam_login_secure", ""))
        self._hotkeys(self.token)
        self.b_paste = self.btn(line, "Вставить", self.paste_token, width=84, height=38)
        self.b_paste.grid(row=0, column=1, padx=(6, 0))
        self.b_token = self.btn(p, "Сохранить и переподключиться", self.save_token, height=36)
        self.b_token.grid(row=2, column=0, sticky="ew", padx=6, pady=(8, 6))
        ctk.CTkLabel(p, text="Берётся в браузере: F12 → Application → Cookies → "
                            "steamcommunity.com → steamLoginSecure. Это ключ от сессии "
                            "аккаунта, никому его не показывай.",
                     text_color=t["muted"], anchor="w", font=self.font(10), wraplength=380,
                     justify="left").grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.b_appdir = self.btn(p, f"Настройки лежат в {core.APP_DIR.name} — открыть",
                                 self.open_app_dir, height=30)
        self.b_appdir.configure(font=self.font(10))
        self.b_appdir.grid(row=4, column=0, sticky="ew", padx=6, pady=(0, 10))

    def _footer(self) -> None:
        t = self.t
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=4, column=0, sticky="ew", padx=18, pady=(2, 12))
        foot.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(foot, text="Подключаюсь…", text_color=t["muted"],
                                   anchor="w", font=self.font(11))
        self.status.grid(row=0, column=0, sticky="ew")
        self.picker = ctk.CTkOptionMenu(
            foot, values=list(THEMES), width=132, height=30, corner_radius=t["r"],
            fg_color=t["field"], button_color=t["field"], button_hover_color=t["accent_h"],
            text_color=t["text"], dropdown_fg_color=t["card"],
            dropdown_hover_color=t["accent_h"], dropdown_text_color=t["text"],
            font=self.font(11), dropdown_font=self.font(11), command=self.set_theme)
        self.picker.set(self.cfg["theme"])
        self.picker.grid(row=0, column=1, sticky="e", padx=(8, 0))

    # ---------- служебное ----------
    def _count(self, _=None) -> None:
        n = len(self.entry.get().strip())
        self.count.configure(text=f"{n}/32",
                             text_color=self.t["bad"] if n > 32 else self.t["muted"])

    def _toggle_eye(self) -> None:
        self.token.configure(show="" if self.eye.get() else "•")

    def _clip(self, widget, action: str):
        """Ctrl+C/V/X/A своими руками.

        Tk ставит штатные сочетания на keysym, а при русской раскладке под
        Ctrl+V приходит Cyrillic_em — событие <<Paste>> не срабатывает вовсе.
        Поэтому смотрим на keycode физической клавиши, он от раскладки
        не зависит."""
        inner = getattr(widget, "_entry", widget)
        if action == "paste":
            try:
                text = self.clipboard_get()
            except Exception:
                return "break"
            with contextlib.suppress(Exception):
                inner.delete("sel.first", "sel.last")
            inner.insert("insert", "".join(text.split()))  # токен копируют с переносами
        elif action == "all":
            inner.select_range(0, "end")
            inner.icursor("end")
        else:  # copy / cut
            with contextlib.suppress(Exception):
                self.clipboard_clear()
                self.clipboard_append(inner.selection_get())
                if action == "cut":
                    inner.delete("sel.first", "sel.last")
        return "break"

    def _hotkeys(self, widget) -> None:
        keys = {86: "paste", 67: "copy", 88: "cut", 65: "all"}

        def handler(event, w=widget):
            action = keys.get(event.keycode)
            return self._clip(w, action) if action else None

        widget.bind("<Control-KeyPress>", handler)

    def busy(self, on: bool, text: str = "") -> None:
        state = "disabled" if on else "normal"
        for w in (self.b_refresh, self.b_cycle, self.b_set, self.b_add, self.b_token,
                  self.b_pick, self.b_folder, self.b_rescan, self.b_paste, self.b_appdir,
                  self.entry, self.token, self.picker, *self.rows, *self.abtns):
            w.configure(state=state)
        if text:
            self.status.configure(text=text, text_color=self.t["muted"])
        self.configure(cursor="watch" if on else "arrow")

    def say(self, text: str, bad: bool = False) -> None:
        self.status.configure(text=text, text_color=self.t["bad"] if bad else self.t["good"])

    def work(self, fn, done) -> None:
        """Сеть — в отдельном потоке, ответ — через очередь в поток интерфейса."""
        threading.Thread(target=lambda: self.jobs.put((done, run_core(fn))),
                         daemon=True).start()

    def _drain(self) -> None:
        while not self.jobs.empty():
            done, payload = self.jobs.get()
            done(*payload)
        self.after(80, self._drain)

    def fill(self) -> None:
        for w in self.box.winfo_children():
            w.destroy()
        self.rows = []
        t = self.t
        presets = self.cfg.get("presets") or []
        if not presets:
            ctk.CTkLabel(self.box, text="пусто — добавь ник ниже", text_color=t["muted"],
                         font=self.font(11)).grid(row=0, column=0, pady=10)
            return
        inner = max(t["r"] - 4, 0)
        for i, name in enumerate(presets):
            line = ctk.CTkFrame(self.box, fg_color=t["field"], corner_radius=inner,
                                border_width=t["border"], border_color=t["border_c"])
            line.grid(row=i, column=0, sticky="ew", pady=3)
            line.grid_columnconfigure(0, weight=1)
            pick = ctk.CTkButton(line, text=name, anchor="w", height=34, corner_radius=inner,
                                 fg_color="transparent", hover_color=t["accent_h"],
                                 text_color=t["text"], font=self.font(12),
                                 command=lambda n=name: self.change(n))
            pick.grid(row=0, column=0, sticky="ew")
            kill = ctk.CTkButton(line, text="✕", width=34, height=34, corner_radius=inner,
                                 fg_color="transparent", hover_color=t["danger"],
                                 text_color=t["muted"], font=self.font(12),
                                 command=lambda n=name: self.del_preset(n))
            kill.grid(row=0, column=1, padx=(0, 2))
            self.rows += [pick, kill]

    def save_cfg(self) -> bool:
        """Пишем конфиг рядом с программой. Если папка только для чтения —
        говорим об этом вслух, а не молча теряем настройки."""
        try:
            core.CONFIG.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), "utf-8")
            return True
        except OSError as e:
            self.say(f"Не смог записать {core.CONFIG.name}: {e.strerror or e}. "
                     "Перенеси программу в папку, куда разрешена запись.", bad=True)
            return False

    # ---------- аватарки ----------
    def _image(self, source, side: int):
        """CTkImage из файла или байтов. None, если Pillow нет или файл битый."""
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
            im = im.convert("RGB")
            im.thumbnail((side, side), Image.LANCZOS)
            img = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self.thumbs.append(img)  # держим ссылку, иначе картинку съест сборщик мусора
            return img
        except Exception:
            return None

    def fill_avatars(self) -> None:
        for w in self.abox.winfo_children():
            w.destroy()
        self.abtns, self.thumbs = [], []
        files = core.avatar_files()
        if not files:
            ctk.CTkLabel(self.abox, text=f"Пусто. Кинь картинки в папку\n{core.AVATARS}",
                         text_color=self.t["muted"], font=self.font(11),
                         justify="center").grid(row=0, column=0, columnspan=3, pady=14)
            return
        inner = max(self.t["r"] - 4, 0)
        for i, path in enumerate(files):
            img = self._image(path, 84)
            b = ctk.CTkButton(self.abox, image=img, text="" if img else path.stem[:12],
                              width=100, height=100, corner_radius=inner,
                              fg_color=self.t["field"], hover_color=self.t["accent_h"],
                              text_color=self.t["text"], font=self.font(10),
                              border_width=self.t["border"], border_color=self.t["border_c"],
                              command=lambda p=path: self.upload(p))
            b.grid(row=i // 3, column=i % 3, padx=4, pady=4)
            self.abtns.append(b)

    def show_preview(self) -> None:
        if not self.session or not self.avatar_link:
            return

        def done(blob, msg):
            img = self._image(blob, 54) if blob else None
            if img:
                self.pic_img = img  # отдельная ссылка: список превьюшек чистится при пересборке
                self.pic.configure(image=img, text="")

        self.work(lambda: self.session.get(self.avatar_link, timeout=20).content, done)

    def upload(self, path) -> None:
        if not self.session:
            return self.say("Сначала подключись — нужен рабочий токен.", bad=True)
        self.busy(True, f"Загружаю {Path(path).name}…")

        def done(ok, msg):
            self.busy(False)
            self.say(msg or ("Аватар обновлён." if ok else "Steam не принял картинку"),
                     bad=not ok)
            if ok:
                self.connect()  # перечитать профиль и показать новое превью

        self.work(lambda: core.set_avatar(self.session, self.steamid, self.sid, path), done)

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Картинка для аватара", initialdir=str(core.AVATARS if
                                                         core.AVATARS.is_dir() else core.HERE),
            filetypes=[("Картинки", "*.png *.jpg *.jpeg *.gif"), ("Все файлы", "*.*")])
        if path:
            self.upload(path)

    def open_folder(self) -> None:
        core.prepare_dirs()
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(core.AVATARS)
        self.say(f"Папка открыта: {core.AVATARS}")

    def open_app_dir(self) -> None:
        core.prepare_dirs()
        with contextlib.suppress(OSError, AttributeError):
            os.startfile(core.APP_DIR)
        self.say(str(core.APP_DIR))

    def paste_token(self) -> None:
        """Кнопка на случай, если Ctrl+V всё-таки не дошёл."""
        self.token.delete(0, "end")
        self._clip(self.token, "paste")
        value = self.token.get().strip()
        self.say(f"Вставлено {len(value)} символов." if value
                 else "В буфере обмена пусто.", bad=not value)

    # ---------- действия ----------
    def set_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        nick, was, tab = self.entry.get().strip(), self.now.cget("text"), self.tabs.get()
        self.cfg["theme"] = name
        saved = self.save_cfg()
        self.t = THEMES[name]
        ctk.set_appearance_mode(self.t["mode"])
        self.build(keep_nick=nick, tab=tab)
        self.now.configure(text=was)
        if saved:
            self.say(f"Оформление: {name}")
        else:
            self.say(f"Тема применена, но {core.CONFIG.name} не записался — "
                     "после перезапуска вернётся прежняя.", bad=True)

    def connect(self) -> None:
        if not self.cfg.get("steam_login_secure"):
            self.now.configure(text="—")
            return self.say("Вставь токен на вкладке «Токен» и сохрани.", bad=True)
        self.busy(True, "Читаю профиль…")

        def job():
            self.session, self.steamid, self.sid = core.open_session(
                self.cfg["steam_login_secure"])
            data = core.profile_data(self.session, self.steamid)
            return core.current_name(data), core.avatar_url(data)

        def done(pair, msg):
            self.busy(False)
            name, link = pair or ("", "")
            self.avatar_link = link
            self.now.configure(text=name or "—")
            self.say(f"Подключено к {self.steamid}." if name else (msg or "Не подключился"),
                     bad=not name)
            self.show_preview()

        self.work(job, done)

    def change(self, name: str) -> None:
        if not name:
            return self.say("Ник пустой.", bad=True)
        if not self.session:
            return self.say("Сначала подключись — нужен рабочий токен.", bad=True)
        self.busy(True, f"Ставлю «{name}»…")

        def done(ok, msg):
            self.busy(False)
            if ok:
                self.now.configure(text=name)
                self.entry.delete(0, "end")
                self._count()
                self.say(msg or f"Готово: {name}")
            else:
                self.say(msg or "Steam не принял ник", bad=True)

        self.work(lambda: core.set_name(self.session, self.steamid, self.sid, name), done)

    def cycle(self) -> None:
        presets = self.cfg.get("presets") or []
        if not presets:
            return self.say("Пресетов нет.", bad=True)
        self.change(core.pick_preset(presets, None))

    def add_preset(self) -> None:
        name = self.entry.get().strip()
        presets = self.cfg.setdefault("presets", [])
        if not name:
            return self.say("Сначала впиши ник.", bad=True)
        if name in presets:
            return self.say("Такой пресет уже есть.", bad=True)
        presets.append(name)
        if not self.save_cfg():
            presets.remove(name)  # на диск не легло — не делаем вид, что легло
            return
        self.fill()
        self.say(f"«{name}» в пресетах.")

    def del_preset(self, name: str) -> None:
        self.cfg["presets"].remove(name)
        if not self.save_cfg():
            self.cfg["presets"].append(name)
            return self.fill()
        self.fill()
        self.say(f"«{name}» убран.")

    def save_token(self) -> None:
        value = self.token.get().strip().strip('"')
        if not value:
            return self.say("Поле токена пустое.", bad=True)
        self.cfg["steam_login_secure"] = value
        if not self.save_cfg():
            return
        self.eye.deselect()
        self._toggle_eye()
        self.say("Токен сохранён, проверяю…")
        self.connect()


if __name__ == "__main__":
    App().mainloop()







