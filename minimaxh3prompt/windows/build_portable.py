#!/usr/bin/env python3
"""Build a portable Windows 11 (x64) package of the h3kit GUI. Runs on any OS.

    python3 windows/build_portable.py            # -> windows/dist/H3PromptKit-win64.zip

The package has its own Python (python-build-standalone, checksum-verified), so nothing has to be
installed on the Windows machine: unzip, double-click "Start H3 Prompt Kit.bat".
"""
import hashlib
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = "3.12.10"
PBS_TAG = "20250409"
ASSET = f"cpython-{PY_VERSION}+{PBS_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/"

KIT = Path(__file__).resolve().parent.parent          # minimaxh3prompt/
HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
CACHE = HERE / ".cache"
APP_FILES = ["h3kit.py", "h3kit_gui.py", "gui.html", "README_ru.md"]

# parts of the stdlib the GUI never uses: drop them to keep the zip small
DROP = ["include", "libs", "Scripts", "tcl", "Lib/site-packages", "Lib/test", "Lib/idlelib", "Lib/tkinter",
        "Lib/turtledemo", "Lib/ensurepip", "Lib/lib2to3", "Lib/pydoc_data", "Lib/venv", "Lib/turtle.py",
        "DLLs/_tkinter.pyd", "DLLs/tcl86t.dll", "DLLs/tk86t.dll"]

BAT = r"""@echo off
rem H3 Prompt Kit: local web GUI. Close this window to stop it.
chcp 65001 >nul
title H3 Prompt Kit
"%~dp0runtime\python.exe" -E -B -X utf8 "%~dp0app\h3kit_gui.py" %*
if errorlevel 1 (
  echo.
  echo Something went wrong, see the message above.
  pause
)
"""

BAT_LAN = r"""@echo off
rem Same GUI, but Ollama is on another computer: edit the address below.
chcp 65001 >nul
title H3 Prompt Kit (remote Ollama)
"%~dp0runtime\python.exe" -E -B -X utf8 "%~dp0app\h3kit_gui.py" --ollama http://192.168.1.133:11434 %*
if errorlevel 1 pause
"""

README = """H3 Prompt Kit — портативная версия для Windows 11 (x64)

Запуск
  1. Распакуйте архив в любую папку (не запускайте прямо из архива).
  2. Дважды щёлкните "Start H3 Prompt Kit.bat".
     Откроется браузер с адресом http://127.0.0.1:7861 (если порт занят — следующий свободный).
  3. Чтобы остановить — закройте чёрное окно.

Ollama
  - Должна быть запущена (https://ollama.com). По умолчанию адрес http://localhost:11434.
  - Другой адрес можно ввести прямо в GUI (поле «Ollama» сверху) — он запоминается.
  - Ollama на другом компьютере: на нём задайте OLLAMA_HOST=0.0.0.0, а здесь укажите его адрес,
    например http://192.168.1.133:11434 (или используйте "Start H3 Prompt Kit (remote Ollama).bat",
    поправив адрес внутри файла Блокнотом).

Параметры запуска (можно дописать в .bat после %*)
  --port 8000        другой порт
  --no-browser       не открывать браузер
  --host 0.0.0.0     открыть GUI для других компьютеров в сети (осторожно: без пароля)

Внутри
  runtime\\   собственный Python {py} (ничего не нужно устанавливать)
  app\\       h3kit.py, h3kit_gui.py, gui.html, prompts\\ — можно обновлять, заменяя файлы

Если Windows SmartScreen предупредит о .bat — «Подробнее» → «Выполнить в любом случае».
""".format(py=PY_VERSION)


def fetch(name):
    CACHE.mkdir(exist_ok=True)
    p = CACHE / name
    if not p.exists():
        print("download", name)
        with urllib.request.urlopen(BASE + name, timeout=300) as r:
            p.write_bytes(r.read())
    return p


def main():
    tar = fetch(ASSET)
    sums = fetch("SHA256SUMS").read_text()
    want = next(line.split()[0] for line in sums.splitlines() if line.endswith(ASSET))
    got = hashlib.sha256(tar.read_bytes()).hexdigest()
    if got != want:
        sys.exit(f"checksum mismatch for {ASSET}: {got} != {want}")
    print("checksum OK")

    stage = DIST / "H3PromptKit"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "runtime").mkdir(parents=True)
    with tarfile.open(tar) as t:
        for m in t.getmembers():
            if not m.name.startswith("python/") or m.issym() or m.islnk():
                continue
            rel = m.name[len("python/"):]
            if not rel or any(rel == d or rel.startswith(d + "/") for d in DROP) or "__pycache__" in rel:
                continue
            dest = stage / "runtime" / rel
            if m.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(t.extractfile(m).read())

    app = stage / "app"
    app.mkdir()
    for f in APP_FILES:
        shutil.copy2(KIT / f, app / f)
    shutil.copytree(KIT / "prompts", app / "prompts", ignore=shutil.ignore_patterns("__pycache__", ".*"))

    crlf = lambda s: s.replace("\r\n", "\n").replace("\n", "\r\n")
    (stage / "Start H3 Prompt Kit.bat").write_bytes(crlf(BAT).encode("ascii"))
    (stage / "Start H3 Prompt Kit (remote Ollama).bat").write_bytes(crlf(BAT_LAN).encode("ascii"))
    (stage / "README.txt").write_bytes(b"\xef\xbb\xbf" + crlf(README).encode("utf-8"))

    out = DIST / "H3PromptKit-win64.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, Path("H3PromptKit") / p.relative_to(stage))
    print(f"{out}  {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
