#!/usr/bin/env python3
"""h3kit — make weak local LLMs (Qwen 3.6, 8B and smaller) write correct MiniMax H3 video prompts.

Idea: everything that can be computed is computed in Python (shot plan, cut times, picture-alignment
line, trigger placement hints, dialogue blocks with language tags). The LLM only writes the scene.
Then deterministic auto-fixes + validator + retry with the error list.

Variants (system prompts in ./prompts):
  t2va     text -> video (default)
  i2va     animate a first frame                       (--mode I2VA)
  fl2va    first + last frame / only last frame         (--mode FL2VA | L2VA)
  talking  talking head / UGC / interview with dialogue
  product  product shot / ad
  story    video longer than 15 s -> chain of clips (planner + t2va per clip)
  ref      reference to video (Ref2VA): up to 9 images, 3 videos, 3 audios   (--ref "image|subject|...")
  slots    JSON slot filling + Python assembly (for the tiniest models, 1–4B)

CLI:
  h3kit.py build    --request "..." --duration 10 [...]   # print variant, system prompt path, user message
  h3kit.py run      --model qwen3.6:35b-a3b --request "..." --duration 10 [...]
  h3kit.py validate prompt.txt --duration 10 [...]
  h3kit.py assemble slots.json --duration 10 [...]
  h3kit.py export                                          # write standalone prompts to prompts/built/
Python 3.8+, no dependencies.
"""
import argparse
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
VARIANTS = ["t2va", "i2va", "fl2va", "talking", "product", "ref", "story", "slots"]

# ---------------------------------------------------------------- request ----

def make_request(request="", duration=8, aspect="16:9", mode="T2VA", triggers="", dialogue="",
                 text="", image="", start="", end="", variant="auto", shots=None, refs=None, **_):
    return {
        "request": request.strip(), "duration": int(duration), "aspect": aspect, "mode": mode.upper(),
        "triggers": parse_triggers(triggers) if isinstance(triggers, str) else triggers,
        "dialogue": parse_dialogue(dialogue) if isinstance(dialogue, str) else dialogue,
        "text": [t.strip() for t in re.split(r"\s*\|\s*|\n", text) if t.strip()] if isinstance(text, str) else text,
        "image": image.strip(), "start": start.strip(), "end": end.strip(),
        "variant": variant, "shots": shots,
        "refs": [parse_ref(r) for r in (refs or [])],
    }


def route(req):
    """Pick a variant deterministically. No LLM needed."""
    if req["variant"] != "auto":
        return req["variant"]
    if req.get("refs"):
        return "ref"
    if req["duration"] > 15:
        return "story"
    if req["mode"] == "I2VA":
        return "i2va"
    if req["mode"] in ("FL2VA", "L2VA"):
        return "fl2va"
    r = req["request"].lower()
    if re.search(r"product|packshot|ad\b|advert|реклам|товар|продукт|упаковк|флакон|бутыл", r):
        return "product"
    if req["dialogue"]:
        return "talking"
    return "t2va"

# ------------------------------------------------------------- shot plan ----

def fmt_time(t):
    return f"{int(t // 60):02d}:{int(t % 60):02d}.{int(round((t % 1) * 1000)):03d}"


def plan_shots(duration, mode="T2VA", n=None):
    """Return list of (start, end). Every shot >= 3 s."""
    d = int(duration)
    if n is None:
        if mode in ("FL2VA", "L2VA") or d <= 6:
            n = 1
        elif d <= 12:
            n = 2
        else:
            n = 3
    n = max(1, min(int(n), d // 3, 3))
    if n == 1:
        return [(0, d)]
    if n == 2:
        cut = 4 if d <= 9 else d // 2
        return [(0, cut), (cut, d)]
    a, b = round(d / 3), round(2 * d / 3)
    return [(0, a), (a, b), (b, d)]


def cut_line(i, start):
    return f"[Shot {i}] At {fmt_time(start)}, the camera cuts to"


def alignment_line(mode, duration, n_shots):
    s = f"{float(duration):.2f}"
    if mode == "I2VA":
        return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    if mode == "FL2VA":
        return ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
                f"0.00-second mark of the target video; Picture 2 (from Shot {n_shots}) aligns with the {s}-second mark of the target video.")
    if mode == "L2VA":
        return ("How the reference pictures align with the target video — <Picture 1> (from [Shot "
                f"{n_shots}]) aligns with the {s}-second mark of the target video.")
    return ""

# -------------------------------------------------------- triggers & text ----

ROLES = {"style", "subject", "object", "place"}


def parse_triggers(s):
    out = []
    for t in re.split(r"[,\n]", s or ""):
        t = t.strip()
        if not t:
            continue
        role = "style"
        if ":" in t and t.split(":", 1)[0].strip().lower() in ROLES:
            role, t = [x.strip() for x in t.split(":", 1)]
            role = role.lower()
        out.append((role, t))
    return out


TRIGGER_HINT = {
    "style": "in the first sentence of Shot 1, right after the style (\"Live-action, cinematic, {w} look,\")",
    "subject": "right before the noun of the main character, first time it appears (\"a {w} <noun>\", e.g. woman / man / cat)",
    "object": "right before the noun of that object, first time it appears (\"the {w} <noun>\", e.g. car / bottle / robot)",
    "place": "right before the noun of the place (\"on a {w} <noun>\", e.g. road / street / beach)",
}


def detect_lang(s):
    if re.search(r"[぀-ヿ]", s): return "Japanese"
    if re.search(r"[가-힯]", s): return "Korean"
    if re.search(r"[一-鿿]", s): return "Chinese"
    if re.search(r"[؀-ۿ]", s): return "Arabic"
    if re.search(r"[А-Яа-яЁё]", s): return "Russian"
    if re.search(r"[ñ¿¡]", s): return "Spanish"
    if re.search(r"[äöüß]", s): return "German"
    if re.search(r"[àâçéèêëîïôûùœ]", s): return "French"
    return "English"


def parse_dialogue(s):
    """Lines separated by newline or ' | '. Optional 'S2:' prefix and '[Language]' prefix."""
    out = []
    for line in re.split(r"\s*\|\s*|\n", s or ""):
        line = line.strip()
        if not line:
            continue
        sid = "S1"
        m = re.match(r"^\(?(S\d(?:,S\d)*)\)?\s*:\s*(.+)$", line)
        if m:
            sid, line = m.group(1), m.group(2).strip()
        lang = None
        m = re.match(r"^\[([A-Za-z]+)\]\s*(.+)$", line)
        if m:
            lang, line = m.group(1), m.group(2)
        out.append({"id": sid, "lang": lang or detect_lang(line), "text": line})
    return out


def d_block(d):
    return f"<d>[{d['lang']}] {d['text']}</d>"


def assign_dialogue(dialogue, shots):
    """Put lines into shots: as late as possible but within ~2.5 words/s."""
    if not dialogue:
        return []
    budget = [(e - s) * 2.5 for s, e in shots]
    words = [len(d["text"].split()) for d in dialogue]
    # start from the last shot and go backwards
    res = [None] * len(dialogue)
    si = len(shots) - 1
    for li in range(len(dialogue) - 1, -1, -1):
        while si > 0 and budget[si] < words[li]:
            si -= 1
        res[li] = si + 1
        budget[si] -= words[li]
    # keep order non-decreasing
    for i in range(1, len(res)):
        res[i] = max(res[i], res[i - 1])
    return res


def dialogue_warning(req):
    words = sum(len(d["text"].split()) for d in req["dialogue"])
    if words > req["duration"] * 2.5:
        return f"WARNING: {words} words of dialogue for {req['duration']} s is too much (max ~{int(req['duration'] * 2.5)})."
    return ""

# ------------------------------------------------------------ user message ----

def build_user_message(req, variant=None):
    variant = variant or route(req)
    if variant == "ref":
        return build_ref_user_message(req)
    shots = plan_shots(req["duration"], req["mode"], req["shots"])
    L = [f"REQUEST: {req['request']}", f"DURATION: {req['duration']} seconds"]
    a = req["aspect"]
    if a in ("9:16", "3:4"):
        L.append(f"ASPECT: {a} (vertical: main subject in the center, medium shot or closer)")
    elif a in ("21:9",):
        L.append(f"ASPECT: {a} (very wide: use wide shots, place subjects on the left or right third)")
    else:
        L.append(f"ASPECT: {a}")
    if req["mode"] == "I2VA":
        L.append("FIRST FRAME: <Picture 1>" + (f" shows: {req['image']}" if req["image"] else " (describe it as 'the ... shown in <Picture 1>')"))
    if req["mode"] == "FL2VA":
        L.append(f"START = Picture 1" + (f": {req['start']}" if req["start"] else ""))
        L.append(f"END = Picture 2" + (f": {req['end']}" if req["end"] else ""))
    if req["mode"] == "L2VA":
        L.append(f"END = <Picture 1>" + (f": {req['end']}" if req["end"] else ""))
    L.append("SHOT PLAN:")
    for i, (s, e) in enumerate(shots, 1):
        if i == 1:
            L.append(f"- [Shot 1] {s}–{e} s, starts with \"[Shot 1] \" (no time)")
        else:
            L.append(f"- [Shot {i}] {s}–{e} s, starts with \"{cut_line(i, s)}\"")
    if req["triggers"]:
        L.append("TRIGGER WORDS (each exactly once, unchanged, never in quotes):")
        for role, w in req["triggers"]:
            L.append(f"- {w} → " + TRIGGER_HINT[role].format(w=w))
    else:
        L.append("TRIGGER WORDS: none")
    if req["dialogue"]:
        where = assign_dialogue(req["dialogue"], shots)
        L.append("DIALOGUE BLOCKS (copy exactly, put a speaker description before each):")
        for d, sh in zip(req["dialogue"], where):
            L.append(f"- in Shot {sh}: ({d['id']}) says: {d_block(d)}")
    else:
        L.append("DIALOGUE BLOCKS: none — nobody speaks")
    if req["text"]:
        L.append("ON-SCREEN TEXT (put in double quotes, exactly): " + " | ".join(f'"{t}"' for t in req["text"]))
    else:
        L.append("ON-SCREEN TEXT: none — use no double quotes")
    return "\n".join(L)


def load_system(variant):
    if variant == "story":
        return (PROMPTS / "story_planner.md").read_text(encoding="utf-8")
    if variant == "slots":
        return (PROMPTS / "slots.md").read_text(encoding="utf-8")
    core = (PROMPTS / "_core.md").read_text(encoding="utf-8")
    part = (PROMPTS / f"{variant}.md").read_text(encoding="utf-8")
    if variant == "ref":
        # same rules, different output sections and style placement
        a, b = core.index("# OUTPUT"), core.index("# SHOTS")
        core = core[:a] + REF_OUTPUT + core[b:]
        core = re.sub(r"- \[Shot 1\] begins with the style:.*?\n", REF_STYLE, core, count=1)
        core = core.replace("no line about pictures (it is added automatically)",
                            "no subject_definitions and no retention_analysis (they are added automatically)")
    return core.rstrip() + "\n\n" + part.strip() + "\n"


REF_OUTPUT = """# OUTPUT: exactly four sections, separated by one empty line

summary: <starts with the given SUMMARY prefix, then 1–2 sentences using the reference labels>

detailed_description: <one paragraph: one style sentence, then all shots>

overall_soundscape: <1–4 sentences: real sounds of the scene>

non_diegetic_music: <1–3 sentences: background music, or N/A>

Write in English. Copy as-is (do not translate): reference labels like <Subject 1>, trigger words, dialogue blocks, on-screen text.

"""
REF_STYLE = ("- detailed_description begins with ONE style sentence before [Shot 1]: \"The target video is in a "
             "<live-action cinematic / 3D CG / 2D-animated / anime / claymation> style with <light phrase>.\"\n")

# --------------------------------------------------------------- auto-fix ----

FIELDS = ["integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"]


def strip_think(t):
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"^.*?</think>", "", t, flags=re.S) if "</think>" in t else t
    t = re.sub(r"\n-{3,}\s*\n\s*<think>.*$", "", t, flags=re.S)  # trailing reasoning dump
    t = re.sub(r"<think>.*$", "", t, flags=re.S)
    return t


def autofix(text, req):
    """Cheap deterministic repairs. Returns (text, list_of_fixes)."""
    fixes = []
    t = strip_think(text)
    t = re.sub(r"```[a-z]*", "", t)
    # markdown around field names
    for f in FIELDS:
        t2 = re.sub(r"[*_#>\s]*\**" + f + r"\**\s*\**\s*:\s*\**", "\n\n" + f + ": ", t)
        if t2 != t:
            t = t2
    # drop chatter before first field and any picture line written by the model
    i = t.find(FIELDS[0] + ":")
    if i > 0:
        if t[:i].strip():
            fixes.append("removed text before integrated_multimodal_description")
        t = t[i:]
    # each field on its own paragraph, single-line body
    parts = {}
    for k, f in enumerate(FIELDS):
        m = re.search(f + r":\s*(.*?)(?=\n\s*(?:" + "|".join(FIELDS) + r"):|$)", t, flags=re.S)
        if m:
            parts[f] = re.sub(r"\s+", " ", m.group(1)).strip()
    if len(parts) == 3:
        t = "\n\n".join(f"{f}: {parts[f]}" for f in FIELDS)
    # trigger prefixes and quotes
    for role, w in req["triggers"]:
        if re.search(rf"\b(?:style|subject|object|place):\s*{re.escape(w)}", t):
            t = re.sub(rf"\b(?:style|subject|object|place):\s*({re.escape(w)})", r"\1", t)
            fixes.append(f"removed prefix before {w}")
        if f'"{w}"' in t:
            t = t.replace(f'"{w}"', w)
            fixes.append(f"removed quotes around {w}")
        # keep only first occurrence
        occ = [m.start() for m in re.finditer(re.escape(w), t)]
        if len(occ) > 1:
            head, tail = t[:occ[0] + len(w)], t[occ[0] + len(w):]
            tail = re.sub(re.escape(w) + r"\s?", "", tail)
            t = head + tail
            fixes.append(f"removed repeated trigger {w}")
    # cut times: the plan is authoritative -> rewrite them
    plan = plan_shots(req["duration"], req["mode"], req["shots"])
    t2 = re.sub(r"\[Shot 1\]\s*At \d+:\d+(?:\.\d+)?,?\s*", "[Shot 1] ", t)

    def _cut(m):
        i = int(m.group(1))
        if i == 1 or i > len(plan):
            return m.group(0)
        return cut_line(i, plan[i - 1][0]) + " "
    t2 = re.sub(r"\[Shot (\d+)\]\s*(?:At \d+:\d+(?:\.\d+)?,?\s*)?(?:(?:the (?:camera|shot) (?:cuts|transitions|changes|switches) to)\s*)?",
                _cut, t2, flags=re.I)
    if t2 != t:
        t = t2
        fixes.append("normalized cut lines to SHOT PLAN")
    # dialogue punctuation
    if "</d>." in t or "</d>," in t:
        t = re.sub(r"</d>[.,]", "</d>", t)
        fixes.append("removed punctuation after </d>")
    # forbidden camera modifiers
    bad_speed = r"\s*,?\s*at (?:a |an )?(?:moderate|medium|normal|steady|gentle|constant|leisurely|smooth|steady|even|controlled)\s+(?:speed|pace)"
    if re.search(bad_speed, t, flags=re.I):
        t = re.sub(bad_speed, "", t, flags=re.I)
        fixes.append("removed non-standard speed")
    if re.search(r"\s*with (?:a )?(?:medium|moderate|normal) amplitude", t, flags=re.I):
        t = re.sub(r"\s*with (?:a )?(?:medium|moderate|normal) amplitude", "", t, flags=re.I)
        fixes.append("removed non-standard amplitude")
    t2 = re.sub(r"\b(The camera) (?:slowly|gently|smoothly|steadily|quickly|subtly) ", r"\1 ", t)
    if t2 != t:
        t = t2
        fixes.append("removed adverb before camera verb")
    # model-written alignment lines -> drop, then add the correct one
    t = re.sub(r"^\s*(For the target video.*?referenced\.|How the reference pictures align.*?target video\.)\s*", "", t, flags=re.S)
    line = alignment_line(req["mode"], req["duration"], len(plan_shots(req["duration"], req["mode"], req["shots"])))
    if line:
        t = line + "\n\n" + t.strip()
    return t.strip() + "\n", fixes

# --------------------------------------------------------------- validate ----

CAM_VERBS = ["holds", "pushes", "pulls", "zooms", "pans", "tilts", "trucks", "pedestals", "arcs", "tracks", "shakes", "rolls"]
SIZES = ["extreme wide shot", "wide shot", "medium-wide shot", "medium wide shot", "medium shot", "medium close-up",
         "close-up", "extreme close-up", "close shot", "full shot", "long shot"]
POSITION = ["third", "center", "centre", "foreground", "midground", "background", "edge", "fills the frame", "<picture", "picture 1"]
BANNED = ["masterpiece", "8k", "4k", "ultra-detailed", "hyperrealistic", "drone shot", "dolly zoom", "fpv", "stunning", "breathtaking"]


def split_fields(text):
    pos = [text.find(f + ":") for f in FIELDS]
    if any(p < 0 for p in pos) or pos != sorted(pos):
        return None
    return [text[pos[i] + len(FIELDS[i]) + 1:(pos[i + 1] if i < 2 else len(text))].strip() for i in range(3)]


def validate(text, req, variant=None):
    if (variant or route(req)) == "ref":
        return validate_ref(text, req)
    err = []
    shots_plan = plan_shots(req["duration"], req["mode"], req["shots"])
    line = alignment_line(req["mode"], req["duration"], len(shots_plan))
    body = text.strip()
    if line:
        if not body.startswith(line):
            err.append("first line must be the exact picture-alignment line")
        body = body[len(line):].strip() if body.startswith(line) else body
    elif body.startswith(("For the target video", "How the reference")):
        err.append("T2VA must not have a picture-alignment line")
    f = split_fields(body)
    if not f:
        return err + ["need three fields in order: integrated_multimodal_description, overall_soundscape, non_diegetic_music"]
    imd, snd, mus = f

    # shots
    if not imd.startswith("[Shot 1]"):
        err.append("integrated_multimodal_description must start with [Shot 1]")
    if re.match(r"\[Shot 1\]\s*At\s", imd):
        err.append("[Shot 1] must not have a time")
    shots = [s for s in re.split(r"(?=\[Shot \d+\])", imd) if s.strip()]
    if len(shots) != len(shots_plan):
        err.append(f"need exactly {len(shots_plan)} shot(s) as in SHOT PLAN, got {len(shots)}")
    for i, (s, e) in enumerate(shots_plan[1:], 2):
        if cut_line(i, s) not in imd:
            err.append(f"Shot {i} must start with: {cut_line(i, s)}")
    for i, s in enumerate(shots, 1):
        low = s.lower()
        # camera moves: any "the camera <known verb>", plus sentence-initial "The camera <unknown verb>"
        cams = [c for c in re.findall(r"\bthe camera (\w+)", low) if c in CAM_VERBS]
        n = len(cams) + len(re.findall(r"\bthe shot is a pov\b", low))
        heads = re.findall(r"(?:^|[.!?]\s+|\]\s+)The camera (\w+)", s)
        unknown = [c for c in heads if c.lower() not in CAM_VERBS and c.lower() != "cuts"]
        if unknown:
            err.append(f"Shot {i}: unknown camera verb '{unknown[0]}' — use a phrase from the camera list")
        if n == 0:
            err.append(f"Shot {i}: no camera sentence (e.g. 'The camera holds a static shot.')")
        elif n > 1:
            err.append(f"Shot {i}: {n} camera sentences — keep exactly one")
        for cam in re.findall(r"the camera [^.]*\.", low):
            for m in re.findall(r"at (?:a |an )?\w+ (?:speed|pace)", cam):
                if m not in ("at slow speed", "at fast speed"):
                    err.append(f"Shot {i}: '{m}' is not allowed — use 'at slow speed' / 'at fast speed' or nothing")
            for m in re.findall(r"with (?:a )?\w+ amplitude", cam):
                if m not in ("with small amplitude", "with large amplitude"):
                    err.append(f"Shot {i}: '{m}' is not allowed — use 'with small/large amplitude' or nothing")
        if not any(sz in low for sz in SIZES):
            err.append(f"Shot {i}: name the shot size (wide shot / medium shot / close-up ...)")
    if shots and not any(p in shots[0].lower() for p in POSITION):
        err.append("Shot 1: give the position in frame (left third / center / right third / foreground ...)")
    if shots and "by the end of the shot" not in shots[-1].lower() and "at the end of the shot" not in shots[-1].lower():
        err.append("last shot: describe the final state with 'By the end of the shot ...'")

    # triggers
    for role, w in req["triggers"]:
        c = imd.count(w)
        if c == 0:
            err.append(f"trigger word missing: {w} ({TRIGGER_HINT[role].format(w=w)})")
        elif c > 1:
            err.append(f"trigger word {w} used {c} times — exactly once")
        if f'"{w}' in text or f'{w}"' in text:
            err.append(f"trigger word {w} must not be in quotes")

    # dialogue
    blocks = re.findall(r"<d>.*?</d>", imd, flags=re.S)
    if not req["dialogue"] and blocks:
        err.append("dialogue was invented — DIALOGUE BLOCKS is none, remove all <d> blocks")
    if req["dialogue"]:
        where = assign_dialogue(req["dialogue"], shots_plan)
        for d, sh in zip(req["dialogue"], where):
            b = d_block(d)
            if b not in imd:
                err.append(f"dialogue block missing or changed, copy exactly: {b}")
            elif shots and len(shots) >= sh and b not in shots[sh - 1]:
                err.append(f"dialogue block {b} must be in Shot {sh}")
            if b in imd and not re.search(r"\(" + re.escape(d["id"]) + r"\)(?:[^<]|<(?:Audio|Subject) \d+>){0,140}" + re.escape(b), imd):
                err.append(f"put the speaker ID ({d['id']}) right before {b}, e.g. 'The old man with a low voice ({d['id']}) says: {b}'")
        if len(blocks) > len(req["dialogue"]):
            err.append("extra dialogue was invented — use only the given DIALOGUE BLOCKS")

    # on-screen text / quotes
    quoted = re.findall(r'"([^"]+)"', re.sub(r"<d>.*?</d>", "", body))
    for q in quoted:
        if q not in req["text"]:
            err.append(f'"{q}" is in quotes but is not ON-SCREEN TEXT — remove the quotes')
    for t in req["text"]:
        if f'"{t}"' not in imd:
            err.append(f'on-screen text missing, add exactly: "{t}"')

    # sound
    nsent = len(re.findall(r"[.!?](?:\s|$)", snd))
    if not snd or snd.upper() == "N/A" and req["variant"] != "silent":
        err.append("overall_soundscape: write 1–4 sentences of real sounds")
    elif nsent > 4:
        err.append(f"overall_soundscape: max 4 sentences (got {nsent})")
    if "<d>" in snd or "<d>" in mus:
        err.append("no dialogue in overall_soundscape / non_diegetic_music")
    if not mus:
        err.append("non_diegetic_music is empty — describe music or write N/A")
    elif mus.upper() != "N/A" and len(re.findall(r"[.!?](?:\s|$)", mus)) > 3:
        err.append("non_diegetic_music: max 3 sentences")

    # language and style
    rest = re.sub(r'<d>.*?</d>|"[^"]*"', "", body, flags=re.S)
    for _, w in req["triggers"]:
        rest = rest.replace(w, "")
    if re.search(r"[А-Яа-яЁё一-鿿]", rest):
        err.append("write everything in English (only dialogue blocks and on-screen text keep their language)")
    for b in BANNED:
        if re.search(r"\b" + re.escape(b) + r"\b", body.lower()):
            err.append(f"remove '{b}'")
    return err

# -------------------------------------------------------- slots assembler ----

CAMERA_SLOTS = {
    "static": ("The camera holds a static shot", None, False),
    "push_in": ("The camera pushes in", "toward", True),
    "pull_out": ("The camera pulls out", "from", True),
    "zoom_in": ("The camera zooms in", "on", True),
    "zoom_out": ("The camera zooms out", "from", True),
    "pan_left": ("The camera pans left", "toward", True),
    "pan_right": ("The camera pans right", "toward", True),
    "tilt_up": ("The camera tilts up", "toward", True),
    "tilt_down": ("The camera tilts down", "toward", True),
    "truck_left": ("The camera trucks left", "past", True),
    "truck_right": ("The camera trucks right", "past", True),
    "pedestal_up": ("The camera pedestals up", "toward", True),
    "pedestal_down": ("The camera pedestals down", "toward", True),
    "arc": ("The camera arcs around", "", True),
    "track": ("The camera tracks", "", True),
    "pov": ("The shot is a POV from", "", False),
    "shake_slight": ("The camera shakes slightly", None, False),
    "shake_strong": ("The camera shakes strongly", None, False),
    "roll_cw": ("The camera rolls clockwise", None, False),
    "roll_ccw": ("The camera rolls counterclockwise", None, False),
}
SLOT_SIZES = ["extreme wide shot", "wide shot", "medium-wide shot", "medium shot", "medium close-up", "close-up", "extreme close-up"]
SLOT_ANGLES = ["eye-level", "low-angle", "high-angle", "top-down", "over-the-shoulder"]
SLOT_POS = ["on the left third of the frame", "in the center of the frame", "on the right third of the frame"]
SLOT_DEPTH = ["in the foreground", "in the midground", "in the background"]
SLOT_FACING = ["facing the camera", "in profile facing left", "in profile facing right", "with the back to the camera", "-"]
SLOT_STYLES = ["Live-action, cinematic", "3D CG", "2D-animated", "anime", "claymation", "watercolor", "vintage film"]


def slots_schema(n_shots):
    s = {"type": "string"}
    shot = {"type": "object", "properties": {
        "size": {"enum": SLOT_SIZES}, "angle": {"enum": SLOT_ANGLES}, "position": {"enum": SLOT_POS},
        "depth": {"enum": SLOT_DEPTH}, "facing": {"enum": SLOT_FACING}, "action": s,
        "camera": {"enum": list(CAMERA_SLOTS)}, "amplitude": {"enum": ["none", "small", "large"]},
        "speed": {"enum": ["none", "slow", "fast"]}, "target": s, "end_state": s},
        "required": ["size", "angle", "position", "depth", "facing", "action", "camera", "amplitude", "speed", "target", "end_state"]}
    return {"type": "object", "properties": {
        "style": {"enum": SLOT_STYLES}, "light": s, "subject": s, "subject_short": s, "voice": s, "place": s,
        "object": s, "shots": {"type": "array", "items": shot, "minItems": n_shots, "maxItems": n_shots},
        "soundscape": s, "music": s},
        "required": ["style", "light", "subject", "subject_short", "voice", "place", "object", "shots", "soundscape", "music"]}


def _art(word):
    return "an" if word[:1].lower() in "aeiou" else "a"


def _insert_trigger(phrase, w):
    """'a young woman' + w -> 'a w young woman'"""
    m = re.match(r"^(a|an|the)\s+(.*)$", phrase.strip(), flags=re.I)
    if m:
        art = m.group(1)
        if art.lower() in ("a", "an"):
            art = _art(w)
        return f"{art} {w} {m.group(2)}"
    return f"{w} {phrase.strip()}"


def _sent(s):
    s = s.strip().rstrip(".")
    return (s[:1].upper() + s[1:] + ".") if s else ""


def assemble_slots(data, req):
    if isinstance(data, str):
        data = json.loads(extract_json(data))
    plan = plan_shots(req["duration"], req["mode"], req["shots"])
    shots = data["shots"][:len(plan)]
    if len(shots) < len(plan):
        raise ValueError(f"need {len(plan)} shots in JSON, got {len(shots)}")
    trig = {r: [] for r in ROLES}
    for role, w in req["triggers"]:
        trig[role].append(w)
    style = data["style"] if data["style"] in SLOT_STYLES else "Live-action, cinematic"
    style_part = ", ".join([style] + [f"{w} look" for w in trig["style"]] + [data.get("light", "").strip()])
    subject = data["subject"].strip()
    for w in trig["subject"]:
        subject = _insert_trigger(subject, w)
    place = data["place"].strip()
    for w in trig["place"]:
        place = _insert_trigger(place, w)
    obj = (data.get("object") or "").strip()
    for w in trig["object"]:
        if obj and obj.lower() not in ("-", "none"):
            obj = _insert_trigger(obj, w)
        else:  # no separate object -> object trigger goes to the subject
            subject = _insert_trigger(subject, w)
    short = (data.get("subject_short") or "the subject").strip()
    voice = (data.get("voice") or "calm").strip()
    where = assign_dialogue(req["dialogue"], plan)
    out = []
    for i, sh in enumerate(shots, 1):
        size, angle = sh["size"], sh["angle"]
        framing = f"{_art(angle)} {angle} {size}"
        loc = ", ".join(x for x in [sh["position"], sh["depth"], "" if sh["facing"] in ("-", "") else sh["facing"]] if x)
        loc = loc.replace("with the back to", "with its back to")
        if i == 1:
            if req["mode"] == "I2VA":
                head = f"[Shot 1] {style_part}, the scene begins exactly as shown in <Picture 1>: {framing} frames {subject} {loc}, in {place}, preserving appearance, clothing and colors."
            else:
                head = f"[Shot 1] {style_part}, {framing} frames {subject} {loc}, in {place}."
            if obj and obj.lower() not in ("-", "none"):
                head += f" {_sent('Next to ' + short + ' is ' + obj)}"
        else:
            head = f"{cut_line(i, plan[i - 1][0])} {framing} of {short} {loc}."
        cam_key = sh["camera"] if sh["camera"] in CAMERA_SLOTS else "static"
        verb, prep, mods = CAMERA_SLOTS[cam_key]
        cam = verb
        if mods:
            if sh.get("amplitude") in ("small", "large"):
                cam += f" with {sh['amplitude']} amplitude"
            if sh.get("speed") in ("slow", "fast"):
                cam += f" at {sh['speed']} speed"
        tgt = (sh.get("target") or short).strip()
        if cam_key == "pov":
            cam = f"The shot is a POV from {tgt}'s eyes"
        elif cam_key in ("arc", "track"):
            base = "The camera arcs around" if cam_key == "arc" else "The camera tracks"
            cam = cam.replace(base, f"{base} {tgt}" + (" as it moves" if cam_key == "track" else ""))
        elif prep:
            cam += f" {prep} {tgt}"
        parts = [head, _sent(sh["action"]), cam + "."]
        for d, s_i in zip(req["dialogue"], where):
            if s_i == i:
                who = short[:1].upper() + short[1:]
                parts.append(f"{who} with a {voice} voice ({d['id']}) says: {d_block(d)}")
        if req["text"] and i == len(shots):
            parts.append(" ".join(f'A clean title reading "{t}" appears and holds steady.' for t in req["text"]))
        end = sh.get("end_state", "").strip().rstrip(".")
        if end:
            end = re.sub(r"^(by the end of the shot,?\s*)", "", end, flags=re.I)
            parts.append(f"By the end of the shot {end[:1].lower() + end[1:]}.")
        out.append(" ".join(p for p in parts if p))
    imd = " ".join(out)
    music = (data.get("music") or "N/A").strip() or "N/A"
    text = f"integrated_multimodal_description: {imd}\n\noverall_soundscape: {data['soundscape'].strip()}\n\nnon_diegetic_music: {music}\n"
    line = alignment_line(req["mode"], req["duration"], len(plan))
    return (line + "\n\n" + text) if line else text


def extract_json(t):
    t = strip_think(t)
    t = re.sub(r"```(?:json)?", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in model output")
    return t[i:j + 1]

# ------------------------------------------------------------------ story ----

def split_story(total, max_clip=15, target=10):
    n = max(1, math.ceil(total / max_clip), round(total / target))
    base, rem = divmod(int(total), n)
    durs = [base + (1 if k < rem else 0) for k in range(n)]
    if any(d < 4 for d in durs):
        n = max(1, total // 4)
        base, rem = divmod(int(total), n)
        durs = [base + (1 if k < rem else 0) for k in range(n)]
    return durs


def story_user_message(req, durs):
    L = [f"REQUEST: {req['request']}", f"TOTAL: {req['duration']} seconds", f"CLIP COUNT: {len(durs)}",
         "CLIP DURATIONS: " + ", ".join(f"clip {i}: {d} s" for i, d in enumerate(durs, 1))]
    if req["dialogue"]:
        L.append("DIALOGUE LINES (copy exactly into the 'lines' of the clip where they are said):")
        L += [f"- {d['text']}" for d in req["dialogue"]]
    else:
        L.append("DIALOGUE LINES: none")
    return "\n".join(L)


def story_clip_requests(plan, req, durs):
    clips = plan["clips"][:len(durs)]
    reqs = []
    by_text = {d["text"]: d for d in req["dialogue"]}
    for k, (c, d) in enumerate(zip(clips, durs), 1):
        lines = [by_text[x] for x in c.get("lines", []) if x in by_text]
        r = dict(req)
        r.update(duration=d, variant="talking" if lines else "t2va", shots=None, dialogue=lines,
                 request=(f"{c['beat']} Start of the clip: {c['start']} End of the clip: {c['end']} "
                          f"Characters (describe exactly like this): {plan['character']} Style: {plan['style']}."),
                 text=req["text"] if k == len(durs) else [])
        reqs.append(r)
    return reqs

# ------------------------------------------------------- reference to video ----
# Ref2VA: up to 9 images, 3 videos, 3 audios (12 total). Python writes subject_definitions,
# the summary prefix and retention_analysis; the LLM writes summary text + detailed_description + sound.

REF_ROLES = {
    "image": ["subject", "scene", "style", "prop", "first_frame", "last_frame"],
    "video": ["subject", "motion", "camera", "edit", "continue"],
    "audio": ["voice", "music_copy", "music_ref", "sound_copy"],
}
SUBJECT_ROLES = {"subject", "scene", "style", "prop", "motion"}
REF_FIELDS = ["subject_definitions", "summary", "retention_analysis", "detailed_description",
              "overall_soundscape", "non_diegetic_music"]
TASK_ORDER = ["video editing", "video continuation", "keyframe completion", "reference generation",
              "audio reuse", "audio reference"]


def parse_ref(r):
    """'image|subject|young woman in a blue cardigan|S1' -> dict"""
    if isinstance(r, dict):
        d = dict(r)
    else:
        p = [x.strip() for x in r.split("|")]
        d = {"kind": p[0].lower(), "role": (p[1] if len(p) > 1 else "").lower(), "desc": p[2] if len(p) > 2 else "",
             "sid": p[3] if len(p) > 3 and p[3] else None}
    d["kind"] = {"img": "image", "picture": "image", "photo": "image", "vid": "video", "sound": "audio"}.get(d["kind"], d["kind"])
    if d["kind"] not in REF_ROLES:
        raise ValueError(f"ref kind must be image/video/audio: {r}")
    if not d.get("role"):
        d["role"] = REF_ROLES[d["kind"]][0]
    if d["role"] not in REF_ROLES[d["kind"]]:
        raise ValueError(f"role '{d['role']}' not allowed for {d['kind']}; use one of {REF_ROLES[d['kind']]}")
    d["desc"] = (d.get("desc") or "").strip().rstrip(".")
    if d["role"] in SUBJECT_ROLES:  # "<Subject 1> is the {desc}" -> drop the article
        d["desc"] = re.sub(r"^(a|an|the)\s+", "", d["desc"], flags=re.I)
    d.setdefault("sid", None)
    return d


def ref_context(req):
    """Number labels, write definitions, task types, anchors and hints."""
    refs = req["refs"]
    cnt = {"image": 0, "video": 0, "audio": 0}
    n_subj = 0
    plan = plan_shots(req["duration"], req["mode"], req["shots"])
    last = len(plan)
    items, defs, tasks, anchors, hints = [], [], set(), [], []
    for r in refs:
        cnt[r["kind"]] += 1
        k = cnt[r["kind"]]
        src = {"image": f"<Picture {k}>", "video": f"<Video {k}>", "audio": f"<Audio {k}>"}[r["kind"]]
        it = dict(r, src=src, label=None)
        role, desc = r["role"], r["desc"]
        if role in SUBJECT_ROLES:
            n_subj += 1
            lab = f"<Subject {n_subj}>"
            it["label"] = lab
            if role == "scene":
                defs.append(f"{lab} is the environment in {src}: {desc}.")
            elif role == "style":
                defs.append(f"{lab} is the visual style of {src}: {desc}.")
            elif role == "motion":
                defs.append(f"{lab} is the movement from {src}: {desc}.")
            else:
                defs.append(f"{lab} is the {desc} in {src}.")
            tasks.add("reference generation")
        elif role == "first_frame":
            it["label"] = src
            defs.append(f"{src} is the first frame of [Shot 1], showing {desc}.")
            tasks.add("keyframe completion")
            anchors.append(("first", src))
        elif role == "last_frame":
            it["label"] = src
            defs.append(f"{src} is the last frame of [Shot {last}], showing {desc}.")
            tasks.add("keyframe completion")
            anchors.append(("last", src))
        elif role == "camera":
            it["label"] = src
            defs.append(f"{src} is the reference for camera movement, cuts and pacing: {desc}.")
            tasks.add("reference generation")
            anchors.append(("camera", src))
        elif role == "edit":
            it["label"] = src
            defs.append(f"{src} is the source video for the target video edit" + (f", showing {desc}." if desc else "."))
            tasks.add("video editing")
            anchors.append(("edit", src))
        elif role == "continue":
            it["label"] = src
            defs.append(f"{src} is the source video that the target video continues from its final moment" + (f", showing {desc}." if desc else "."))
            tasks.add("video continuation")
            anchors.append(("continue", src))
        items.append(it)
    # audio after subjects are known (voice links to the subject with the same speaker ID)
    for it in items:
        if it["kind"] != "audio":
            continue
        role, desc, src = it["role"], it["desc"], it["src"]
        it["label"] = src
        if role == "voice":
            sid = it["sid"] or "S1"
            it["sid"] = sid
            owner = next((x["label"] for x in items if x.get("sid") == sid and x["role"] in SUBJECT_ROLES), None)
            defs.append(f"{src} is the voice-timbre reference for {owner} ({sid})." if owner
                        else f"{src} is the voice-timbre reference for the speaker ({sid}): {desc}.")
            tasks.add("audio reference")
            anchors.append(("voice", src))
        elif role == "music_copy":
            defs.append(f"{src} is the background music reused as the audience-only score.")
            tasks.add("audio reuse")
        elif role == "music_ref":
            defs.append(f"{src} is the music-style reference for the audience-only score: {desc}.")
            tasks.add("audio reference")
            anchors.append(("music_ref", src))
        elif role == "sound_copy":
            defs.append(f"{src} is the complete audio track reused as the final soundtrack.")
            tasks.add("audio reuse")
    prefix = "[" + " + ".join(t for t in TASK_ORDER if t in tasks) + "]"
    edit = next((s for a, s in anchors if a == "edit"), None)
    if edit:
        prefix += f" The target video is an edited version of {edit}."
    return {"items": items, "defs": defs, "prefix": prefix, "anchors": anchors, "n_shots": last}


def ref_warnings(req):
    c = {"image": 0, "video": 0, "audio": 0}
    for r in req["refs"]:
        c[r["kind"]] += 1
    w = []
    if c["image"] > 9: w.append("max 9 images")
    if c["video"] > 3: w.append("max 3 videos")
    if c["audio"] > 3: w.append("max 3 audios")
    if sum(c.values()) > 12: w.append("max 12 references in total")
    if c["audio"] and not (c["image"] or c["video"]): w.append("audio cannot be the only reference")
    if req["duration"] > 15: w.append("Ref2VA clip is max 15 s")
    return w


def build_ref_user_message(req):
    ctx = ref_context(req)
    shots = plan_shots(req["duration"], req["mode"], req["shots"])
    L = [f"REQUEST: {req['request']}", f"DURATION: {req['duration']} seconds", f"ASPECT: {req['aspect']}",
         "REFERENCES (use these labels exactly, with angle brackets):"]
    L += [f"- {d}" for d in ctx["defs"]]
    L.append(f"SUMMARY must start with: {ctx['prefix']}")
    must = []
    for a, s in ctx["anchors"]:
        if a == "first":
            must.append(f"Shot 1 begins from {s}: write \"the shot begins from {s}\".")
        elif a == "last":
            must.append(f"The last shot ends on {s}: write \"the shot ends on {s}\" in Shot {ctx['n_shots']}.")
        elif a == "continue":
            must.append(f"Shot 1 continues seamlessly from the final moment of {s}.")
        elif a == "edit":
            must.append(f"Describe what changes compared with {s}; mention {s} in Shot 1.")
        elif a == "camera":
            must.append(f"Follow the camera movement and pacing of {s}: write \"following the camera movement of {s}\" in one shot.")
        elif a == "voice":
            must.append(f"When the speaker talks, write \"using the voice timbre referenced from {s}\".")
        elif a == "music_ref":
            must.append(f"non_diegetic_music starts with \"Following the style of {s},\".")
    subj = [it for it in ctx["items"] if it["role"] in SUBJECT_ROLES]
    if subj:
        must.append("Every " + ", ".join(it["label"] for it in subj) + " must appear in the description; at its first appearance repeat its look and give its position in frame.")
    if must:
        L.append("MUST:")
        L += [f"- {m}" for m in must]
    L.append("SHOT PLAN:")
    for i, (s, e) in enumerate(shots, 1):
        L.append(f"- [Shot 1] {s}–{e} s, starts with \"[Shot 1] \" (no time)" if i == 1
                 else f"- [Shot {i}] {s}–{e} s, starts with \"{cut_line(i, s)}\"")
    if req["triggers"]:
        L.append("TRIGGER WORDS (each exactly once in detailed_description, unchanged, never in quotes):")
        for role, w in req["triggers"]:
            hint = (f"in the style sentence (\"The target video is in a live-action cinematic {w} style with ...\")"
                    if role == "style" else TRIGGER_HINT[role].format(w=w))
            L.append(f"- {w} → " + hint)
    else:
        L.append("TRIGGER WORDS: none")
    if req["dialogue"]:
        where = assign_dialogue(req["dialogue"], shots)
        L.append("DIALOGUE BLOCKS (copy exactly):")
        for d, sh in zip(req["dialogue"], where):
            owner = next((it["label"] for it in ctx["items"] if it.get("sid") == d["id"] and it["role"] in SUBJECT_ROLES), None)
            who = f"{owner} ({d['id']})" if owner else f"<voice description> ({d['id']})"
            L.append(f"- in Shot {sh}: {who} says: {d_block(d)}")
    else:
        L.append("DIALOGUE BLOCKS: none — nobody speaks")
    L.append("ON-SCREEN TEXT (in double quotes, exactly): " + " | ".join(f'"{t}"' for t in req["text"])
             if req["text"] else "ON-SCREEN TEXT: none — use no double quotes")
    return "\n".join(L)


def _ref_parts(t):
    names = ["summary", "detailed_description", "overall_soundscape", "non_diegetic_music"]
    out = {}
    for f in names:
        m = re.search(r"(?:^|\n)\s*[*#]*\s*" + f + r"\s*[*]*\s*:\s*(.*?)(?=\n\s*[*#]*\s*(?:" + "|".join(REF_FIELDS) + r")\s*[*]*\s*:|$)", t, flags=re.S)
        if m:
            out[f] = re.sub(r"\s+", " ", m.group(1)).strip()
    return out


def autofix_ref(text, req):
    fixes = []
    ctx = ref_context(req)
    t = strip_think(text).replace("```", "")
    t2 = re.sub(r"<\s*(subject|picture|video|audio)\s+(\d+)\s*>", lambda m: f"<{m.group(1).capitalize()} {m.group(2)}>", t, flags=re.I)
    t2 = re.sub(r"(?<![<\w])(Subject|Picture|Video|Audio) (\d+)(?![>\d])", r"<\1 \2>", t2)
    if t2 != t:
        t = t2
        fixes.append("normalized reference labels")
    p = _ref_parts(t)
    if "summary" in p:
        s = re.sub(r"^\[[^\]]*\]\s*", "", p["summary"])
        s = s.replace("The target video is an edited version of", "").strip() if "edited version" in ctx["prefix"] else s
        if not p["summary"].startswith(ctx["prefix"]):
            fixes.append("set summary prefix")
        p["summary"] = (ctx["prefix"] + " " + s).strip()
    if "detailed_description" in p:
        dd, f2 = autofix("integrated_multimodal_description: " + p["detailed_description"] +
                         "\n\noverall_soundscape: x.\n\nnon_diegetic_music: N/A", dict(req, mode="T2VA"))
        p["detailed_description"] = dd.split("\n\n")[0].replace("integrated_multimodal_description: ", "", 1)
        fixes += [f for f in f2 if "text before" not in f]
    for it in ctx["items"]:
        if it["role"] == "music_copy":
            p["non_diegetic_music"] = f"{it['src']} is directly reused as the complete audience-only score."
        if it["role"] == "sound_copy":
            p["overall_soundscape"] = f"{it['src']} is reused 1:1 as the complete soundtrack of the target video."
            p.setdefault("non_diegetic_music", "N/A")
    return p, fixes


def _shots_of(dd):
    return [s for s in re.split(r"(?=\[Shot \d+\])", dd) if s.startswith("[Shot")]


RETAIN = {"subject": ("fully_preserved", "the {d} is retained with the same identity and look."),
          "scene": ("fully_preserved", "the environment ({d}) is retained."),
          "prop": ("fully_preserved", "the {d} keeps its shape, color and material."),
          "style": ("partially_preserved", "the visual style ({d}) is followed for the new content."),
          "motion": ("fully_preserved", "the movement ({d}) and its timing are followed.")}


def assemble_ref(p, req):
    ctx = ref_context(req)
    shots = _shots_of(p.get("detailed_description", ""))
    ret = []
    for it in ctx["items"]:
        lab, role = it["label"], it["role"]
        if role in SUBJECT_ROLES:
            where = [f"[Shot {i}]" for i, s in enumerate(shots, 1) if lab in s] or ["[Shot 1]"]
            mark, why = RETAIN[role]
            ret.append(f"{lab} (appears in {', '.join(where)}): {it.get('keep') or mark} - {why.format(d=it['desc'])}")
        elif role == "first_frame":
            ret.append(f"{lab} ([Shot 1] first frame): fully_preserved - the target video begins exactly from this frame.")
        elif role == "last_frame":
            ret.append(f"{lab} ([Shot {ctx['n_shots']}] last frame): fully_preserved - the target video ends exactly on this frame.")
        elif role == "camera":
            ret.append(f"{lab} (camera movement and pacing): weak_reference - only its camera movement, cut rhythm and pacing are followed.")
        elif role == "edit":
            ret.append(f"{lab} (source video): partially_preserved - the original footage is kept except for the requested changes.")
        elif role == "continue":
            ret.append(f"{lab} (continuation source): fully_preserved - the target video starts from its final state.")
        elif role == "voice":
            ret.append(f"{lab}: reference - the speaker's voice timbre and delivery follow {lab} without copying the original signal.")
        elif role == "music_copy":
            ret.append(f"{lab}: partially_copy - only its music is copied as the audience-only score.")
        elif role == "music_ref":
            ret.append(f"{lab}: reference - only its music style, instrumentation and tempo are referenced.")
        elif role == "sound_copy":
            ret.append(f"{lab}: fully_copy - {lab} is reused 1:1 as the complete final audio track.")
    body = {
        "subject_definitions": "\n".join(ctx["defs"]),
        "summary": p.get("summary", ""),
        "retention_analysis": "\n".join(ret),
        "detailed_description": p.get("detailed_description", ""),
        "overall_soundscape": p.get("overall_soundscape", ""),
        "non_diegetic_music": p.get("non_diegetic_music", "N/A") or "N/A",
    }
    return "\n\n".join(f"{k}:\n{body[k]}" for k in REF_FIELDS) + "\n"


def validate_ref(text, req):
    err = []
    ctx = ref_context(req)
    pos = [text.find(f + ":") for f in REF_FIELDS]
    if any(x < 0 for x in pos) or pos != sorted(pos):
        return ["need six sections in order: " + ", ".join(REF_FIELDS)]
    sec = {f: text[pos[i] + len(f) + 1:(pos[i + 1] if i < 5 else len(text))].strip() for i, f in enumerate(REF_FIELDS)}
    dd, summ = sec["detailed_description"], sec["summary"]
    if not summ.startswith(ctx["prefix"]):
        err.append(f"summary must start with: {ctx['prefix']}")
    defined = set(re.findall(r"<(?:Subject|Picture|Video|Audio) \d+>", sec["subject_definitions"]))
    for lab in set(re.findall(r"<(?:Subject|Picture|Video|Audio) \d+>", summ + dd + sec["overall_soundscape"] + sec["non_diegetic_music"])):
        if lab not in defined:
            err.append(f"{lab} is not defined in REFERENCES — use only the given labels")
    if not re.match(r"The target video\b", dd):
        err.append("detailed_description must start with one style sentence: 'The target video is in a ... style with ...' and then [Shot 1]")
    # reuse the base checks for shots, camera, triggers, dialogue, text
    fake = (f"integrated_multimodal_description: {dd[dd.find('[Shot 1]'):] if '[Shot 1]' in dd else dd}\n\n"
            f"overall_soundscape: {sec['overall_soundscape']}\n\nnon_diegetic_music: {sec['non_diegetic_music']}")
    base = validate(fake, dict(req, mode="T2VA", refs=[], variant="t2va", triggers=[]))
    for role, w in req["triggers"]:
        c = dd.count(w)
        if c != 1:
            err.append(f"trigger word {w} must appear exactly once in detailed_description (now {c})")
    base = [e for e in base if not e.startswith("Shot 1: give the position") or not re.search(r"<(Subject|Picture) \d+>", dd)]
    err += [e for e in base if "picture-alignment" not in e]
    shots = _shots_of(dd)
    for it in ctx["items"]:
        if it["role"] in SUBJECT_ROLES and it["label"] not in dd:
            err.append(f"{it['label']} must appear in detailed_description")
    for a, s in ctx["anchors"]:
        if a in ("first", "continue", "edit") and shots and s not in shots[0]:
            err.append(f"Shot 1 must mention {s}" + (" ('the shot begins from " + s + "')" if a == "first" else ""))
        if a == "last" and shots and s not in shots[-1]:
            err.append(f"the last shot must end on {s} ('the shot ends on {s}')")
        if a in ("camera", "voice") and s not in dd:
            err.append(f"mention {s} in detailed_description")
        if a == "music_ref" and s not in sec["non_diegetic_music"]:
            err.append(f"non_diegetic_music must reference {s}")
    for d in req["dialogue"]:
        owner = next((it["label"] for it in ctx["items"] if it.get("sid") == d["id"] and it["role"] in SUBJECT_ROLES), None)
        if owner and f"{owner} ({d['id']})" not in dd:
            err.append(f"write the speaker as '{owner} ({d['id']})' before {d_block(d)}")
    return err

# ----------------------------------------------------------------- ollama ----

def ollama_chat(messages, model, host="http://localhost:11434", think=False, fmt=None,
                temperature=0.3, num_ctx=8192, num_predict=None, timeout=1800, seed=None, no_think=False):
    if no_think and messages and messages[-1]["role"] == "user":
        # Qwen3's soft switch: thinking models such as qwen3-vl ignore think=false
        # and can burn the whole token budget before writing an answer
        messages = messages[:-1] + [dict(messages[-1], content=messages[-1]["content"] + "\n/no_think")]
    body = {"model": model, "messages": messages, "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx}}
    if num_predict:
        body["options"]["num_predict"] = num_predict
    if seed is not None:  # reproducible sampling; None leaves Ollama's own random seed
        body["options"]["seed"] = int(seed)
    if think is not None:
        body["think"] = think
    if fmt is not None:
        body["format"] = fmt
    rq = urllib.request.Request(host.rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"]


def generate(req, model, host="http://localhost:11434", retries=2, think=False, verbose=True, **kw):
    variant = route(req)
    if variant == "story":
        return generate_story(req, model, host, retries, think, verbose, **kw)
    system = load_system(variant)
    if variant == "ref":
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": build_ref_user_message(req)}]
        out, errs = "", []
        for attempt in range(retries + 1):
            raw = ollama_chat(msgs, model, host, think, **kw)
            parts, fixes = autofix_ref(raw, req)
            out = assemble_ref(parts, req)
            errs = validate_ref(out, req)
            if verbose:
                print(f"[ref attempt {attempt + 1}] autofix: {fixes} | errors: {errs}", file=sys.stderr)
            if not errs:
                break
            model_part = "\n\n".join(f"{k}: {parts.get(k, '')}" for k in REF_FIELDS[1:] if k != "retention_analysis")
            msgs += [{"role": "assistant", "content": model_part},
                     {"role": "user", "content": "Your answer has these problems:\n- " + "\n- ".join(errs)
                      + "\nRewrite all four sections with these fixes. Output only the sections."}]
        return {"variant": variant, "prompt": out, "errors": errs, "warning": "; ".join(ref_warnings(req))}
    if variant == "slots":
        plan = plan_shots(req["duration"], req["mode"], req["shots"])
        user = build_user_message(req, "slots")
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        errs = []
        for attempt in range(retries + 1):
            raw = ollama_chat(msgs, model, host, think, fmt=slots_schema(len(plan)), **kw)
            try:
                out = assemble_slots(raw, req)
                errs = validate(out, req, variant)
            except Exception as e:  # bad JSON
                out, errs = raw, [f"invalid JSON: {e}"]
            if verbose:
                print(f"[slots attempt {attempt + 1}] errors: {errs}", file=sys.stderr)
            if not errs:
                break
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Fix these problems and output the full JSON again:\n- " + "\n- ".join(errs)}]
        return {"variant": variant, "prompt": out, "errors": errs}
    user = build_user_message(req, variant)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out, errs = "", []
    for attempt in range(retries + 1):
        raw = ollama_chat(msgs, model, host, think, **kw)
        out, fixes = autofix(raw, req)
        errs = validate(out, req, variant)
        if verbose:
            print(f"[{variant} attempt {attempt + 1}] autofix: {fixes} | errors: {errs}", file=sys.stderr)
        if not errs:
            break
        msgs += [{"role": "assistant", "content": out},
                 {"role": "user", "content": "Your prompt has these problems:\n- " + "\n- ".join(errs)
                  + "\nRewrite the WHOLE prompt with these fixes. Output only the prompt."}]
    return {"variant": variant, "prompt": out, "errors": errs, "warning": dialogue_warning(req)}


def generate_story(req, model, host, retries, think, verbose, **kw):
    durs = split_story(req["duration"])
    msgs = [{"role": "system", "content": load_system("story")},
            {"role": "user", "content": story_user_message(req, durs)}]
    schema = {"type": "object", "properties": {
        "style": {"type": "string"}, "character": {"type": "string"},
        "clips": {"type": "array", "minItems": len(durs), "maxItems": len(durs), "items": {
            "type": "object", "properties": {"beat": {"type": "string"}, "start": {"type": "string"},
                                             "end": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}}},
            "required": ["beat", "start", "end", "lines"]}}},
        "required": ["style", "character", "clips"]}
    plan = json.loads(extract_json(ollama_chat(msgs, model, host, think, fmt=schema, **kw)))
    results = []
    for k, r in enumerate(story_clip_requests(plan, req, durs), 1):
        res = generate(r, model, host, retries, think, verbose, **kw)
        res["clip"], res["duration"] = k, r["duration"]
        results.append(res)
    return {"variant": "story", "plan": plan, "clips": results}

# -------------------------------------------------------------------- CLI ----

def _req_from_args(a):
    if getattr(a, "req", None):
        return make_request(**json.loads(Path(a.req).read_text(encoding="utf-8")))
    return make_request(request=a.request or "", duration=a.duration, aspect=a.aspect, mode=a.mode,
                        triggers=a.triggers, dialogue=a.dialogue, text=a.text, image=a.image,
                        start=a.start, end=a.end, variant=a.variant, shots=a.shots, refs=a.ref)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--req", help="JSON file with request fields (alternative to flags)")
        p.add_argument("--request", default="")
        p.add_argument("--duration", type=int, default=8)
        p.add_argument("--aspect", default="16:9")
        p.add_argument("--mode", default="T2VA", help="T2VA | I2VA | FL2VA | L2VA")
        p.add_argument("--triggers", default="", help="'style:x, subject:y, object:z, place:w, plain'")
        p.add_argument("--dialogue", default="", help="lines split by ' | ', optional 'S2:' prefix")
        p.add_argument("--text", default="", help="on-screen text, split by ' | '")
        p.add_argument("--image", default="", help="I2VA: what the first frame shows")
        p.add_argument("--start", default="", help="FL2VA: first frame description")
        p.add_argument("--end", default="", help="FL2VA/L2VA: last frame description")
        p.add_argument("--variant", default="auto", choices=["auto"] + VARIANTS)
        p.add_argument("--shots", type=int, default=None, help="force number of shots (1–3)")
        p.add_argument("--ref", action="append", default=[],
                       help="Ref2VA reference 'kind|role|description[|S1]', repeat. kinds/roles: "
                            "image: subject scene style prop first_frame last_frame; "
                            "video: subject motion camera edit continue; audio: voice music_copy music_ref sound_copy")

    p = sub.add_parser("build")
    common(p)
    p = sub.add_parser("run")
    common(p)
    p.add_argument("--model", required=True)
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--think", action="store_true")
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--num-predict", type=int, default=None)
    p.add_argument("--num-ctx", type=int, default=8192)
    p.add_argument("--seed", type=int, default=None, help="sampling seed (default: Ollama picks one)")
    p.add_argument("--no-think", action="store_true", help="append Qwen3's /no_think switch to the last user message")
    p = sub.add_parser("validate")
    common(p)
    p.add_argument("file")
    p.add_argument("--fix", action="store_true")
    p = sub.add_parser("assemble")
    common(p)
    p.add_argument("file")
    sub.add_parser("export")
    a = ap.parse_args()

    if a.cmd == "export":
        out = PROMPTS / "built"
        out.mkdir(exist_ok=True)
        for v in VARIANTS:
            (out / f"{v}.md").write_text(load_system(v), encoding="utf-8")
        print(f"written to {out}")
        return
    req = _req_from_args(a)
    if a.cmd == "build":
        v = route(req)
        print(f"# variant: {v}")
        if v == "story":
            print(story_user_message(req, split_story(req["duration"])))
        elif v == "ref":
            print(build_ref_user_message(req))
            for w in ref_warnings(req):
                print("# WARNING: " + w, file=sys.stderr)
        else:
            print(build_user_message(req, v))
        w = dialogue_warning(req)
        if w:
            print("# " + w, file=sys.stderr)
    elif a.cmd == "validate":
        text = Path(a.file).read_text(encoding="utf-8")
        if a.fix and route(req) == "ref":
            parts, fixes = autofix_ref(text, req)
            text = assemble_ref(parts, req)
            print("# fixes:", fixes, file=sys.stderr)
            print(text)
        elif a.fix:
            text, fixes = autofix(text, req)
            print("# fixes:", fixes, file=sys.stderr)
            print(text)
        errs = validate(text, req)
        print("OK" if not errs else "FAIL\n - " + "\n - ".join(errs), file=sys.stderr)
        sys.exit(1 if errs else 0)
    elif a.cmd == "assemble":
        out = assemble_slots(Path(a.file).read_text(encoding="utf-8"), req)
        print(out)
        errs = validate(out, req)
        print("OK" if not errs else "FAIL\n - " + "\n - ".join(errs), file=sys.stderr)
    elif a.cmd == "run":
        res = generate(req, a.model, a.host, a.retries, a.think, temperature=a.temperature,
                       num_predict=a.num_predict, num_ctx=a.num_ctx, seed=a.seed, no_think=a.no_think)
        if res["variant"] == "story":
            for c in res["clips"]:
                print(f"=== CLIP {c['clip']} ({c['duration']} s) ===")
                print(c["prompt"])
                if c["errors"]:
                    print("# errors:", c["errors"], file=sys.stderr)
        else:
            print(res["prompt"])
            if res["errors"]:
                print("# remaining errors:", res["errors"], file=sys.stderr)
            if res.get("warning"):
                print("# " + res["warning"], file=sys.stderr)


if __name__ == "__main__":
    main()
