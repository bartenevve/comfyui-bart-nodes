import json
import socket
import urllib.error

from . import h3kit
from .selection import InputError, coerce_options, format_report, join_clips


class H3Error(RuntimeError):
    """Ollama couldn't be reached / answered badly. InputError covers bad widget values."""


def build_request(options):
    """The kit's request dict from cleaned widget values (no LLM call).

    Cheap and pure, so `VALIDATE_INPUTS` can run it at queue time: a malformed
    `refs` line or dialogue is reported before any model is asked anything.
    """
    refs = [line.strip() for line in options["refs"].splitlines() if line.strip()]
    try:
        return h3kit.make_request(
            request=options["request"],
            duration=options["duration"],
            aspect=options["aspect"],
            mode=options["mode"],
            triggers=options["triggers"],
            dialogue=options["dialogue"],
            text=options["text"],
            image=options["image"],
            start=options["start"],
            end=options["end"],
            variant=options["variant"],
            shots=options["shots"] or None,
            refs=refs,
        )
    except ValueError as exc:
        raise InputError(str(exc)) from None


def generate(values):
    """Run the kit against Ollama. Returns {variant, clips, text, errors, warnings, report}.

    `text` is the saved-text form (clips joined with marker lines when there is
    more than one). Validator errors that survive the kit's retries do NOT
    raise: the best attempt is returned and the errors go in the report, since
    a prompt that is 95% right is still more useful to edit than an exception.
    """
    options = coerce_options(values)
    if not options["request"].strip():
        raise InputError("request is empty")
    req = build_request(options)

    try:
        result = h3kit.generate(
            req,
            options["model"],
            host=options["ollama_url"],
            retries=options["retries"],
            think=options["think"],
            verbose=False,
            temperature=options["temperature"],
            num_ctx=options["num_ctx"],
            num_predict=options["num_predict"] or None,
            timeout=options["timeout"],
            seed=options["seed"],
            no_think=options["append_no_think"],
        )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            pass
        raise H3Error(f"ollama answered HTTP {exc.code}: {detail or exc.reason}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise H3Error(f"ollama did not answer within {options['timeout']}s") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise H3Error(f"ollama did not answer within {options['timeout']}s") from exc
        raise H3Error(f"cannot reach ollama at {options['ollama_url']}: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise H3Error(f"ollama at {options['ollama_url']} returned an unexpected response ({exc!r})") from exc

    errors = []
    warnings = [w for w in [result.get("warning")] if w]
    if result["variant"] == "story":
        clips = [clip["prompt"] for clip in result["clips"]]
        durations = [clip["duration"] for clip in result["clips"]]
        for clip in result["clips"]:
            errors.extend(f"clip {clip['clip']}: {error}" for error in clip["errors"])
            if clip.get("warning"):
                warnings.append(f"clip {clip['clip']}: {clip['warning']}")
    else:
        clips = [result["prompt"]]
        durations = None
        errors = list(result["errors"])

    clips = [clip.strip() for clip in clips]
    if not any(clips):
        raise H3Error(
            f"model {options['model']!r} returned an empty answer. A thinking model (qwen3-vl, ...) may have spent "
            "its whole token budget reasoning: keep append_no_think on, raise num_predict, or use a non-thinking model."
        )

    return {
        "variant": result["variant"],
        "clips": clips,
        "durations": durations or [options["duration"]],
        "text": join_clips(clips, durations),
        "errors": errors,
        "warnings": warnings,
        "report": format_report(result["variant"], len(clips), errors, warnings),
    }
