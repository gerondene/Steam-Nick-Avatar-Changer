#!/usr/bin/env python3
"""Быстрая смена ника (persona name) и аватара в Steam через веб-сессию.

    python steam_nick.py "Новый ник"   поставить конкретный ник
    python steam_nick.py -p 2          ник из presets[2]
    python steam_nick.py -c            следующий по кругу из presets
    python steam_nick.py -l            показать текущий ник и presets
    python steam_nick.py -a кот.png    поставить аватар из файла
    python steam_nick.py --raw         дампнуть JSON профиля (для отладки)
"""
import argparse
import contextlib
import html
import io
import json
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):  # иначе cp866 калечит русский текст
    if stream is not None:               # под pythonw потоков может не быть вовсе
        stream.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    sys.exit("Нужен requests:  pip install requests")

BASE = "https://steamcommunity.com"
# Папка, откуда запущена программа: в собранном exe __file__ ведёт внутрь
# временного каталога распаковки, поэтому смотрим на сам exe.
HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
# Данные держим не рядом с exe: его качают в «Загрузки», а оттуда файлы легко
# потерять вместе с уборкой папки. Стандартное место для настроек — AppData.
_ROAMING = os.environ.get("APPDATA")
APP_DIR = Path(_ROAMING) / "SteamNick" if _ROAMING else Path.home() / ".steam-nick"
CONFIG = APP_DIR / "config.json"
STATE = APP_DIR / "state.json"
BACKUP = APP_DIR / "profile-backup.json"
AVATARS = APP_DIR / "avatars"       # папка с картинками для быстрой смены
MAX_AVATAR = 1024 * 1024           # лимит Steam на файл аватара
IMG_TYPES = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def prepare_dirs() -> None:
    with contextlib.suppress(OSError):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        AVATARS.mkdir(exist_ok=True)


def migrate(old: Path = HERE) -> list:
    """Разовый перенос настроек из папки программы в APP_DIR."""
    prepare_dirs()
    moved = []
    for src, dst in ((old / "config.json", CONFIG),
                     (old / ".state.json", STATE),
                     (old / "profile-backup.json", BACKUP)):
        if src.is_file() and not dst.exists():
            with contextlib.suppress(OSError):
                shutil.move(str(src), str(dst))
                moved.append(dst.name)
    old_avatars = old / "avatars"
    if old_avatars.is_dir() and old_avatars != AVATARS:
        for pic in old_avatars.iterdir():
            if pic.suffix.lower() in IMG_TYPES and not (AVATARS / pic.name).exists():
                with contextlib.suppress(OSError):
                    shutil.move(str(pic), str(AVATARS / pic.name))
                    moved.append(pic.name)
        with contextlib.suppress(OSError):
            old_avatars.rmdir()  # уйдёт, только если опустела
    return moved


migrate()


def load_config() -> dict:
    if not CONFIG.exists():
        sys.exit(f"Нет настроек в {CONFIG} — открой окно (SteamNick.exe или "
                 "steam_nick_gui.py) и вставь токен на вкладке «Токен».")
    cfg = json.loads(CONFIG.read_text("utf-8"))
    if not cfg.get("steam_login_secure"):
        sys.exit("В config.json пустой steam_login_secure.")
    return cfg


def open_session(cookie: str):
    """sessionid — обычный CSRF-токен: Steam устраивает любой,
    лишь бы cookie и поле формы совпадали."""
    steamid = re.split(r"%7C%7C|\|\|", cookie)[0]
    if not steamid.isdigit():
        sys.exit("В начале steamLoginSecure нет SteamID64 — скопируй значение cookie целиком.")
    sid = secrets.token_hex(12)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.cookies.set("steamLoginSecure", cookie, domain="steamcommunity.com", path="/")
    s.cookies.set("sessionid", sid, domain="steamcommunity.com", path="/")
    return s, steamid, sid

def profile_data(s, steamid: str) -> dict:
    r = s.get(f"{BASE}/profiles/{steamid}/edit/info", timeout=20)
    r.raise_for_status()
    if "/login" in r.url:
        sys.exit("Steam отправил на логин — cookie истёк, скопируй заново.")
    m = re.search(r'data-profile-edit="(.*?)"', r.text, re.S)
    if not m:
        sys.exit("Не нашёл блок данных профиля — Steam поменял вёрстку, нужно править парсер.")
    return json.loads(html.unescape(m.group(1)))


def flatten(data: dict) -> dict:
    """Плоский вид JSON профиля: вложенные объекты вроде LocationData
    поднимаются наверх, скаляры верхнего уровня имеют приоритет."""
    flat = {}
    for key, val in data.items():
        if isinstance(val, dict):
            flat.update(flatten(val))
    for key, val in data.items():
        if isinstance(val, (str, int, float, bool)) or val is None:
            flat[key] = val
    return flat


def pluck(flat: dict, *needles: str) -> str:
    """Значение поля без привязки к точному написанию:
    strSummary / summary / locCountryCode — всё найдётся."""
    for needle in needles:
        n = re.sub(r"[^a-z]", "", needle.lower())
        for key, val in flat.items():
            k = re.sub(r"[^a-z]", "", str(key).lower())
            if k == n or k == "str" + n or k.endswith(n):
                return "" if val is None else str(val)
    return ""


def weblinks(data: dict) -> list:
    for val in data.values():
        if isinstance(val, list) and val and isinstance(val[0], dict):
            if any("url" in str(k).lower() for k in val[0]):
                return val[:3]
    return []


# Поле формы -> варианты имени в JSON профиля.
FIELDS = (
    ("real_name", ("realname",)),
    ("summary", ("summary",)),
    ("customURL", ("customurl", "vanityurl")),
    ("country", ("countrycode", "country")),
    ("state", ("statecode", "state")),
    ("city", ("cityid", "citycode", "city")),
)


def current_name(data: dict) -> str:
    return pluck(flatten(data), "personaname") or "?"


def set_name(s, steamid: str, sid: str, name: str, light: bool = False) -> bool:
    if not 2 <= len(name) <= 32:
        sys.exit(f"Ник должен быть 2–32 символа, у тебя {len(name)}.")

    before = profile_data(s, steamid)
    flat = flatten(before)
    backup = BACKUP
    if not backup.exists():  # страховка на случай, если Steam что-то затрёт
        prepare_dirs()
        with contextlib.suppress(OSError):
            backup.write_text(json.dumps(before, ensure_ascii=False, indent=2), "utf-8")

    if light:
        url = f"{BASE}/actions/PersonaNameEdit"
        payload = {"sessionID": sid, "personaName": name}
    else:
        # Полная форма профиля: существующие поля переотправляем как есть,
        # меняем только personaName — иначе Steam затрёт био и локацию.
        url = f"{BASE}/profiles/{steamid}/edit/"
        payload = {"sessionID": sid, "type": "profileSave", "json": "1",
                   "personaName": name,
                   "hide_profile_awards": "1" if flat.get("bProfileAwardsHidden") else "0"}
        for field, names in FIELDS:
            payload[field] = pluck(flat, *names)
        for i, link in enumerate(weblinks(before), start=1):
            payload[f"weblink_{i}_title"] = pluck(link, "title")
            payload[f"weblink_{i}_url"] = pluck(link, "url")

    r = s.post(url, data=payload, timeout=20,
               headers={"Referer": f"{BASE}/profiles/{steamid}/edit/info",
                        "X-Requested-With": "XMLHttpRequest"})
    after = flatten(profile_data(s, steamid))
    if pluck(after, "personaname") != name:
        print(f"Не сработало: HTTP {r.status_code}, ответ: {r.text[:300].strip() or '(пусто)'}",
              file=sys.stderr)
        if light:
            print("Убери --light: этот эндпоинт у Steam больше не работает.", file=sys.stderr)
        return False

    lost = [f for f in ("summary", "customurl", "realname")
            if pluck(flat, f) and not pluck(after, f)]
    if lost:
        print(f"Внимание: Steam обнулил {', '.join(lost)} — исходные значения в {backup.name}.",
              file=sys.stderr)
    return True


def avatar_url(data: dict) -> str:
    """Ссылка на текущий аватар — из хэша в данных профиля."""
    value = pluck(flatten(data), "avatarhash", "avatarfull", "avatar")
    if value.startswith("http"):
        return value
    return f"https://avatars.steamstatic.com/{value}_full.jpg" if len(value) >= 32 else ""


def prep_avatar(path: Path) -> tuple[bytes, str]:
    """Байты картинки под требования Steam: jpg/png/gif до 1 МБ.
    Крупные пережимаем в JPEG, подбирая размер и качество."""
    fmt = IMG_TYPES.get(path.suffix.lower())
    if not fmt:
        sys.exit(f"Формат {path.suffix or '?'} не подойдёт — нужен jpg, png или gif.")
    data = path.read_bytes()
    if len(data) <= MAX_AVATAR:
        return data, fmt
    if fmt == "gif":
        sys.exit(f"Гифка весит {len(data) // 1024} КБ при лимите 1 МБ — сожми её сам, "
                 "пережимать анимацию я не берусь.")
    try:
        from PIL import Image
    except ImportError:
        sys.exit(f"{path.name}: {len(data) // 1024} КБ при лимите 1 МБ. "
                 "Поставь Pillow (pip install pillow), тогда сожму сам.")
    img = Image.open(path).convert("RGB")
    for side in (1024, 720, 512, 384, 256):
        for quality in (90, 80, 70, 60):
            buf = io.BytesIO()
            small = img.copy()
            small.thumbnail((side, side), Image.LANCZOS)
            small.save(buf, "JPEG", quality=quality, optimize=True)
            if buf.tell() <= MAX_AVATAR:
                print(f"Сжал до {side}px, качество {quality} — {buf.tell() // 1024} КБ.")
                return buf.getvalue(), "jpeg"
    sys.exit("Не удалось уложить картинку в 1 МБ — возьми другую.")


def set_avatar(s, steamid: str, sid: str, path) -> bool:
    path = Path(path)
    if not path.is_file():
        sys.exit(f"Нет файла {path}")
    data, fmt = prep_avatar(path)
    r = s.post(f"{BASE}/actions/FileUploader", timeout=60,
               headers={"Referer": f"{BASE}/profiles/{steamid}/edit/avatar"},
               data={"MAX_FILE_SIZE": str(len(data)), "type": "player_avatar_image",
                     "sId": steamid, "sessionid": sid, "doSub": "1", "json": "1"},
               files={"avatar": (f"avatar.{fmt}", data, f"image/{fmt}")})
    try:
        answer = r.json()
    except ValueError:
        print(f"Steam ответил не JSON (HTTP {r.status_code}): {r.text[:200].strip()}",
              file=sys.stderr)
        return False
    if answer.get("success"):
        print(f"Аватар обновлён: {path.name}, {len(data) // 1024} КБ.")
        return True
    print(f"Steam отказал: {answer.get('message') or answer}", file=sys.stderr)
    return False


def avatar_files() -> list:
    """Список картинок в папке avatars. Папку заводим сами: человек мог скачать
    один exe, и ему некуда складывать файлы."""
    with contextlib.suppress(OSError):
        AVATARS.mkdir(exist_ok=True)
    if not AVATARS.is_dir():
        return []
    return sorted(p for p in AVATARS.iterdir() if p.suffix.lower() in IMG_TYPES)


def pick_preset(presets: list, index: int | None) -> str:
    if not presets:
        sys.exit("В config.json пустой presets.")
    if index is None:  # режим -c: следующий по кругу
        prev = -1
        with contextlib.suppress(OSError, ValueError):  # битый или недоступный файл — не беда
            if STATE.exists():
                prev = json.loads(STATE.read_text("utf-8")).get("i", -1)
        index = (prev + 1) % len(presets)
        with contextlib.suppress(OSError):
            STATE.write_text(json.dumps({"i": index}), "utf-8")
    if not 0 <= index < len(presets):
        sys.exit(f"Нет presets[{index}], их всего {len(presets)}.")
    return presets[index]


def ask(prompt: str) -> str:
    """input(), который не падает с трейсбеком, если стдин закрыт."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "q"


def avatar_submenu(s, steamid: str, sid: str) -> None:
    files = avatar_files()
    if not files:
        print(f"Положи картинки в {AVATARS} — папка пустая или её нет.")
        return
    for i, f in enumerate(files):
        print(f"  [{i}] {f.name}  ({f.stat().st_size // 1024} КБ)")
    choice = ask("\nНомер картинки, путь к файлу или Enter — назад: ")
    if not choice or choice.lower() == "q":
        return
    path = files[int(choice)] if choice.isdigit() and int(choice) < len(files) else Path(choice)
    set_avatar(s, steamid, sid, path)


def menu(s, steamid: str, sid: str, presets: list, light: bool) -> None:
    """Интерактивный режим — для запуска двойным кликом."""
    while True:
        print(f"\nСейчас: {current_name(profile_data(s, steamid))}\n")
        for i, p in enumerate(presets):
            print(f"  [{i}] {p}")
        print("  [c] следующий по кругу")
        print("  [a] аватар")
        print("  [q] выход")
        choice = ask("\nНомер, новый ник или q: ")
        if not choice or choice.lower() in ("q", "quit", "exit"):
            return
        if choice.startswith("-") or choice.lower().startswith(("nick ", "python ")):
            print("Здесь ждут только номер или сам ник — флаги работают в терминале.")
            continue
        if choice.lower() == "a":
            avatar_submenu(s, steamid, sid)
            continue
        if choice.lower() == "c":
            name = pick_preset(presets, None)
        elif choice.isdigit() and int(choice) < len(presets):
            name = presets[int(choice)]
        else:
            name = choice
        if set_name(s, steamid, sid, name, light):
            print(f"Ник теперь: {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Быстрая смена ника в Steam")
    ap.add_argument("name", nargs="?", help="новый ник")
    ap.add_argument("-p", "--preset", type=int, help="индекс из presets")
    ap.add_argument("-c", "--cycle", action="store_true", help="следующий preset по кругу")
    ap.add_argument("-l", "--list", action="store_true", help="показать текущий ник и presets")
    ap.add_argument("-i", "--menu", action="store_true", help="интерактивное меню")
    ap.add_argument("-a", "--avatar", metavar="ФАЙЛ", help="поставить аватар из файла")
    ap.add_argument("--light", action="store_true",
                    help="старый быстрый эндпоинт (сейчас не работает)")
    ap.add_argument("--raw", action="store_true", help="дампнуть JSON профиля")
    a = ap.parse_args()

    cfg = load_config()
    s, steamid, sid = open_session(cfg["steam_login_secure"])
    presets = cfg.get("presets") or []

    if a.raw:
        print(json.dumps(profile_data(s, steamid), ensure_ascii=False, indent=2))
        return

    if a.avatar:
        sys.exit(0 if set_avatar(s, steamid, sid, a.avatar) else 1)

    idle = not (a.name or a.cycle or a.preset is not None or a.list)
    if a.menu or (idle and sys.stdin.isatty()):
        menu(s, steamid, sid, presets, a.light)
        return

    if idle or a.list:
        print(f"Сейчас: {current_name(profile_data(s, steamid))}")
        for i, p in enumerate(presets):
            print(f"  [{i}] {p}")
        return

    name = a.name or pick_preset(presets, None if a.cycle else a.preset)
    if set_name(s, steamid, sid, name, a.light):
        print(f"Ник теперь: {name}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        code = e.code
        if isinstance(code, str):  # sys.exit("текст") — показать до закрытия окна
            print(code, file=sys.stderr)
            code = 1
        if code and sys.stdin.isatty():
            ask("\nEnter — закрыть...")
        sys.exit(code)

