#!/usr/bin/env python3
"""Local web GUI for h3kit (no dependencies).

    python3 h3kit_gui.py                 # http://127.0.0.1:7861, opens the browser
    python3 h3kit_gui.py --port 8000 --no-browser --ollama http://localhost:11434
"""
import argparse
import contextlib
import io
import json
import re
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import h3kit as K

HERE = Path(__file__).resolve().parent
HTML = HERE / "gui.html"
LOCK = threading.Lock()  # one generation at a time (stderr capture is global)
DEFAULT_OLLAMA = "http://localhost:11434"


def req_from(d):
    refs = []
    for r in d.get("refs") or []:
        if (r.get("desc") or "").strip() or r.get("role") in ("edit", "continue", "music_copy", "sound_copy"):
            refs.append({"kind": r.get("kind", "image"), "role": r.get("role", ""), "desc": r.get("desc", ""),
                         "sid": (r.get("sid") or "").strip() or None})
    return K.make_request(
        request=d.get("request", ""), duration=int(d.get("duration") or 8), aspect=d.get("aspect", "16:9"),
        mode=d.get("mode", "T2VA"), triggers=d.get("triggers", ""), dialogue=d.get("dialogue", ""),
        text=d.get("text", ""), image=d.get("image", ""), start=d.get("start", ""), end=d.get("end", ""),
        variant=d.get("variant", "auto"), shots=int(d["shots"]) if str(d.get("shots") or "").strip() else None,
        refs=refs)


def llm_kw(d):
    kw = {"temperature": float(d.get("temperature") or 0.3), "num_ctx": int(d.get("num_ctx") or 12288)}
    if str(d.get("num_predict") or "").strip():
        kw["num_predict"] = int(d["num_predict"])
    return kw


# ------------------------------------------------------------ universal ----

UNIVERSAL = K.PROMPTS / "universal.md"


def guess_from_task(task):
    """Pull duration / triggers / dialogue / refs hints out of free text for a light check."""
    m = re.search(r"(\d{1,3})\s*(?:с\b|сек|секунд|s\b|sec|seconds)", task, flags=re.I)
    dur = int(m.group(1)) if m else 8
    trig = re.findall(r"\b(?:style|subject|object|place):\s*[\w\-.]+", task)
    m = re.search(r"(?:триггер\w*|triggers?|lora)\s*:\s*([^\n.]+)", task, flags=re.I)
    if m and not trig:
        trig = [t.strip() for t in m.group(1).split(",") if t.strip()]
    lines = re.findall(r"[«\"]([^»\"]{2,200})[»\"]", task)
    return dur, ", ".join(trig), lines


def light_check(text, task):
    dur, trig, lines = guess_from_task(task)
    t = K.strip_think(text).replace("```", "").strip()
    i = min([x for x in (t.find("integrated_multimodal_description"), t.find("subject_definitions"),
                         t.find("For the target video"), t.find("How the reference"), t.find("=== CLIP")) if x >= 0] or [0])
    t = t[i:].strip()
    notes = [f"проверка по тексту задания: {dur} с, триггеры: {trig or 'нет'}, реплик найдено: {len(lines)}"]
    errs = []
    if "=== CLIP" in t:
        parts = re.split(r"(?m)^=== CLIP\s*(\d+)\s*\((\d+)\s*s\)\s*===\s*$", t)
        total, out = 0, []
        for k in range(1, len(parts) - 2, 3):
            n, d, blk = parts[k], int(parts[k + 1]), parts[k + 2].strip()
            total += d
            creq = K.make_request(request="x", duration=d, triggers=trig, variant="t2va")
            fixed, fx = K.autofix(blk, creq)
            out.append(f"=== CLIP {n} ({d} s) ===\n{fixed.strip()}")
            if fx:
                notes.append(f"клип {n}, автопочинка: " + "; ".join(fx))
            errs += [f"клип {n}: {e}" for e in K.validate(fixed, creq) if not e.startswith("dialogue")]
        if total and total != dur:
            errs.append(f"сумма клипов {total} с, а в задании {dur} с")
        notes.append("CLIPS: каждый клип проверен по своей длительности из заголовка")
        return "\n\n".join(out) or t, errs, notes
    if t.startswith("subject_definitions"):
        if not all(f + ":" in t for f in K.REF_FIELDS):
            errs.append("REF: нужны шесть секций " + ", ".join(K.REF_FIELDS))
        defined = set(re.findall(r"<(?:Subject|Picture|Video|Audio) \d+>", t.split("summary:")[0]))
        used = set(re.findall(r"<(?:Subject|Picture|Video|Audio) \d+>", t))
        errs += [f"метка {x} не определена в subject_definitions" for x in sorted(used - defined)]
        dd = t.split("detailed_description:")[-1].split("overall_soundscape:")[0]
        for _, w in K.parse_triggers(trig):
            if dd.count(w) != 1:
                errs.append(f"триггер {w} должен быть ровно один раз (сейчас {dd.count(w)})")
        return t, errs, notes
    mode = "I2VA" if t.startswith("For the target video") else ("FL2VA" if "Picture 2 (from Shot" in t[:300]
                                                                 else ("L2VA" if t.startswith("How the reference") else "T2VA"))
    req = K.make_request(request="x", duration=dur, mode=mode, triggers=trig, variant="t2va",
                         dialogue="\n".join(lines) if "<d>" in t else "")
    fixed, fixes = K.autofix(t, req)
    errs = [e for e in K.validate(fixed, req) if not e.startswith("dialogue block")]
    if fixes:
        notes.append("автопочинка: " + "; ".join(fixes))
    return fixed, errs, notes


# --------------------------------------------------------------- server ----

class H(BaseHTTPRequestHandler):
    server_version = "h3kit-gui"

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if self.path.startswith("/api/models"):
            host = self.headers.get("X-Ollama", DEFAULT_OLLAMA)
            try:
                with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=10) as r:
                    names = sorted(m["name"] for m in json.loads(r.read()).get("models", []))
                return self._send(200, {"models": names})
            except Exception as e:
                return self._send(200, {"models": [], "error": f"ollama недоступна: {e}"})
        if self.path == "/api/meta":
            return self._send(200, {"variants": ["auto"] + K.VARIANTS, "roles": K.REF_ROLES,
                                    "default_host": DEFAULT_OLLAMA})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            fn = {"/api/build": self.build, "/api/generate": self.generate, "/api/validate": self.validate,
                  "/api/universal": self.universal, "/api/universal_system": self.universal_system}.get(self.path)
            if not fn:
                return self._send(404, {"error": "not found"})
            self._send(200, fn(d))
        except Exception as e:
            self._send(200, {"error": str(e), "trace": traceback.format_exc()[-1500:]})

    # --- endpoints
    def build(self, d):
        req = req_from(d)
        v = K.route(req)
        if v == "story":
            user = K.story_user_message(req, K.split_story(req["duration"]))
        else:
            user = K.build_user_message(req, v)
        warn = (K.ref_warnings(req) if v == "ref" else []) + ([K.dialogue_warning(req)] if K.dialogue_warning(req) else [])
        return {"variant": v, "system": K.load_system(v), "user": user, "warnings": warn}

    def generate(self, d):
        req = req_from(d)
        host = d.get("host") or DEFAULT_OLLAMA
        buf = io.StringIO()
        t0 = time.time()
        with LOCK, contextlib.redirect_stderr(buf):
            res = K.generate(req, d["model"], host, int(d.get("retries") or 2), bool(d.get("think")),
                             verbose=True, **llm_kw(d))
        res["log"] = buf.getvalue().strip().splitlines()
        res["seconds"] = round(time.time() - t0, 1)
        if res.get("variant") == "story":
            res["prompt"] = "\n\n".join(f"=== CLIP {c['clip']} ({c['duration']} s) ===\n{c['prompt'].strip()}" for c in res["clips"])
            res["errors"] = [f"клип {c['clip']}: {e}" for c in res["clips"] for e in c["errors"]]
        return res

    def validate(self, d):
        req = req_from(d)
        text = d.get("prompt", "")
        if d.get("fix"):
            if K.route(req) == "ref":
                parts, fixes = K.autofix_ref(text, req)
                text = K.assemble_ref(parts, req)
            else:
                text, fixes = K.autofix(text, req)
        else:
            fixes = []
        return {"prompt": text, "errors": K.validate(text, req), "fixes": fixes, "variant": K.route(req)}

    def universal_system(self, d):
        return {"system": UNIVERSAL.read_text(encoding="utf-8")}

    def universal(self, d):
        task = d.get("task", "").strip()
        host = d.get("host") or DEFAULT_OLLAMA
        t0 = time.time()
        msgs = [{"role": "system", "content": UNIVERSAL.read_text(encoding="utf-8")},
                {"role": "user", "content": "TASK: " + task}]
        with LOCK:
            raw = K.ollama_chat(msgs, d["model"], host, bool(d.get("think")), **llm_kw(d))
        text, errs, notes = light_check(raw, task)
        return {"variant": "universal", "prompt": text, "errors": errs, "log": notes,
                "seconds": round(time.time() - t0, 1)}


def main():
    global DEFAULT_OLLAMA
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ollama", default=DEFAULT_OLLAMA)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    DEFAULT_OLLAMA = a.ollama
    srv = None
    for port in range(a.port, a.port + 20):  # the port may be busy (another copy is running)
        try:
            srv = ThreadingHTTPServer((a.host, port), H)
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit(f"нет свободного порта в диапазоне {a.port}-{a.port + 19}")
    url = f"http://{a.host}:{srv.server_address[1]}/"
    print(f"h3kit GUI: {url}")
    print("Окно можно свернуть. Закройте его (или Ctrl+C), чтобы остановить.")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
