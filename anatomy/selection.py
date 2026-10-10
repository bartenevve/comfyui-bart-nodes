import json
import re

# key -> (what the prompt asks the model to look for). Order is the order the
# checks appear in the prompt and in reports.
CHECKS = {
    "extra_limbs": "extra arms, legs, hands or feet (more limbs than a person has, limbs growing from wrong places)",
    "missing_limbs": "missing or truncated limbs that should be visible (an arm or leg that ends abruptly or is absent)",
    "bad_fingers": "wrong finger count (more or fewer than five per hand), fused, extra or melted fingers",
    "smeared_limbs": "smeared, blurred, melted or shapeless hands, arms, legs or feet",
    "impossible_pose": "an anatomically impossible pose (joints bending the wrong way, twisted torso, impossible proportions)",
    "face_deformation": "a deformed face (misplaced, duplicated or missing eyes, nose, mouth, ears)",
    "merged_bodies": "bodies or limbs of different people merged into each other, or an extra head",
}

CUSTOM_KEY = "custom"


class VerdictError(ValueError):
    pass


def selected_keys(enabled, custom_criterion=""):
    """Check keys in report order for the enabled built-in checks (+ custom)."""
    keys = [key for key in CHECKS if key in enabled]
    if custom_criterion.strip():
        keys.append(CUSTOM_KEY)
    return keys


def build_prompt(keys, custom_criterion=""):
    lines = []
    for key in keys:
        description = custom_criterion.strip() if key == CUSTOM_KEY else CHECKS[key]
        lines.append(f'- "{key}": {description}')
    example = ", ".join(
        f'"{key}": {{"found": false, "confidence": 0.0, "note": ""}}' for key in keys
    )
    return (
        "You are inspecting a single image for defects, mostly anatomy errors. "
        "Look carefully, count fingers and limbs one by one, and judge only what "
        "is actually visible. If no person or creature is visible, anatomy checks "
        "find nothing.\n\n"
        "Each line below describes a PROBLEM. For each one answer found=true only "
        "if that problem is actually present in this image; found=false means the "
        "image is fine in that respect (it is not a statement about whether the "
        "description is true of something else).\n"
        + "\n".join(lines)
        + "\n\nFor every check report found, your confidence (0.0 to 1.0) that the "
        "answer is right, and a few words of explanation. Answer with JSON only, in "
        'exactly this shape:\n{"checks": {' + example + "}}"
    )


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "y", "1")
    return False


def _as_confidence(value, found):
    try:
        number = float(value)
    except (TypeError, ValueError):
        # a found defect with no usable confidence counts as fully confident:
        # silently dropping it would let a flagged image through
        return 1.0 if found else 0.0
    if 1.0 < number <= 100.0:
        # models asked for 0.0-1.0 sometimes answer in percent ("85")
        number /= 100.0
    return min(1.0, max(0.0, number))


def _extract_json(text):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise VerdictError(f"no JSON object in model answer: {text[:200]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VerdictError(f"model answer is not valid JSON ({exc}): {text[:200]!r}") from exc


def parse_verdict(text, keys):
    """Parse the model's answer into {key: {found, confidence, note}}.

    Accepts the checks either nested under "checks"/"defects" or at the top
    level. A check the model left out counts as not found; an answer that
    mentions none of the requested checks at all is rejected, since that is
    garbage rather than a clean bill of health.
    """
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise VerdictError("model answer is not a JSON object")
    for wrapper in ("checks", "defects"):
        if isinstance(data.get(wrapper), dict):
            data = data[wrapper]
            break
        if isinstance(data.get(wrapper), list):
            # [{"name": "bad_fingers", "found": ...}, ...] instead of a mapping
            data = {
                str(item.get("name") or item.get("check") or item.get("type") or item.get("id")): item
                for item in data[wrapper]
                if isinstance(item, dict)
            }
            break

    verdict = {}
    seen = 0
    for key in keys:
        entry = data.get(key)
        if isinstance(entry, dict):
            seen += 1
            found = _as_bool(entry.get("found"))
            verdict[key] = {
                "found": found,
                "confidence": _as_confidence(entry.get("confidence"), found),
                "note": str(entry.get("note", ""))[:200],
            }
        elif entry is not None and not isinstance(entry, (dict, list)):
            seen += 1
            found = _as_bool(entry)
            verdict[key] = {"found": found, "confidence": 1.0 if found else 0.0, "note": ""}
        else:
            verdict[key] = {"found": False, "confidence": 0.0, "note": "not reported"}
    if keys and seen == 0:
        raise VerdictError(f"model answer mentions none of the requested checks: {sorted(data)[:8]}")
    return verdict


def decide(verdict, threshold):
    """(passed, failed_check_keys): any found defect with confidence >= threshold fails."""
    failed = [
        key
        for key, result in verdict.items()
        if result["found"] and result["confidence"] >= threshold
    ]
    return (not failed, failed)


def split_indices(passed_flags):
    passed = [i for i, ok in enumerate(passed_flags) if ok]
    failed = [i for i, ok in enumerate(passed_flags) if not ok]
    return passed, failed


def indices_string(indices):
    return ",".join(str(i) for i in indices)


def format_report(results):
    """results: list of {index, passed, failed_checks, checks}."""
    lines = []
    for item in results:
        if item["passed"]:
            lines.append(f"#{item['index']} PASS")
            continue
        details = "; ".join(
            f"{key} ({item['checks'][key]['confidence']:.2f})"
            + (f": {item['checks'][key]['note']}" if item["checks"][key]["note"] else "")
            for key in item["failed_checks"]
        )
        lines.append(f"#{item['index']} FAIL {details}")
    return "\n".join(lines)


def report_json(results):
    return json.dumps(results, ensure_ascii=False, indent=2)
