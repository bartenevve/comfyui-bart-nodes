import http.client
import json
import socket
import urllib.error

from . import clipchat, h3kit
from .selection import InputError, coerce_options, format_report, join_clips

# the variants that read the `refs` widget; the frontend hides it for every other one, so a
# leftover line in it must neither be parsed nor block the run
REF_VARIANTS = ("auto", "ref")

EMPTY_ANSWER_HINT = (
    "A thinking model (qwen3-vl, ...) may have spent its whole token budget reasoning: keep append_no_think on, "
    "raise num_predict, or use a non-thinking model."
)
CLIP_EMPTY_ANSWER_HINT = (
    "A thinking model may have spent its whole token budget reasoning: leave think off, raise num_predict, "
    "or use a non-thinking model."
)


class H3Error(RuntimeError):
    """Ollama couldn't be reached / answered badly. InputError covers bad widget values."""


def _blank(text):
    return not (text or "").strip()


def _error_detail(exc):
    """Ollama's own message from an HTTP error body ({"error": "model not found"}), shortened."""
    try:
        detail = json.loads(exc.read(4096).decode("utf-8")).get("error", "")
    except Exception:  # the body is the peer's: anything unreadable simply isn't shown
        return ""
    return detail[:200] if isinstance(detail, str) else ""


def build_request(options):
    """The kit's request dict from cleaned widget values (no LLM call).

    Cheap and pure, so `VALIDATE_INPUTS` can run it at queue time: a malformed
    `refs` line or dialogue is reported before any model is asked anything.
    """
    refs = []
    if options["variant"] in REF_VARIANTS:
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


def generate(values, clip=None):
    """Run the kit against Ollama, or against `clip` (a text-LLM CLIP of the running graph) when
    one is given. Returns {variant, clips, text, errors, warnings, report}.

    `text` is the saved-text form (clips joined with marker lines when there is
    more than one). Validator errors that survive the kit's retries do NOT
    raise: the best attempt is returned and the errors go in the report, since
    a prompt that is 95% right is still more useful to edit than an exception.
    """
    options = coerce_options(values, server=clip is None)
    if not options["request"].strip():
        raise InputError("request is empty")
    req = build_request(options)

    chat = None
    who, hint = f"model {options['model']!r}", EMPTY_ANSWER_HINT
    if clip is not None:
        if h3kit.route(req) == "slots":
            raise InputError("variant slots needs Ollama (it relies on constrained JSON decoding): unlink the clip input")
        try:
            chat = clipchat.make_chat(clip)
        except clipchat.ClipError as exc:
            raise H3Error(str(exc)) from None
        who, hint = "the CLIP model", CLIP_EMPTY_ANSWER_HINT

    answers = []  # what the model itself wrote, before the kit repairs and pads it
    server = options["ollama_url"]
    try:
        result = h3kit.generate(
            req,
            options["model"],
            chat=chat,
            host=server,
            retries=options["retries"],
            think=options["think"],
            verbose=False,
            temperature=options["temperature"],
            num_ctx=options["num_ctx"],
            num_predict=options["num_predict"] or None,
            timeout=options["timeout"],
            seed=options["seed"],
            # `think` asks for the reasoning, so the switch that turns it off must not be sent
            no_think=options["append_no_think"] and not options["think"],
            on_answer=answers.append,
        )
    except clipchat.ClipError as exc:
        raise H3Error(str(exc)) from exc
    except urllib.error.HTTPError as exc:
        raise H3Error(f"ollama answered HTTP {exc.code}: {_error_detail(exc) or exc.reason}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise H3Error(f"ollama did not answer within {options['timeout']}s") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise H3Error(f"ollama did not answer within {options['timeout']}s") from exc
        raise H3Error(f"cannot reach ollama at {server}: {exc.reason}") from exc
    except (http.client.HTTPException, OSError) as exc:
        # a server that hangs up mid-answer, or is not Ollama at all (an SSH banner, a half-open
        # socket). Only the exception's class is reported: its text can be whatever the peer sent.
        raise H3Error(f"the server at {server} dropped or garbled the connection ({type(exc).__name__})") from exc
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        # not JSON, JSON of the wrong shape, a story plan without clips, ... never echoed: it may carry the body
        if answers and all(_blank(answer) for answer in answers):
            raise H3Error(f"{who} returned an empty answer. {hint}") from exc
        origin = "the CLIP model" if clip is not None else f"the server at {server}"
        raise H3Error(f"{origin} returned an unusable answer ({type(exc).__name__})") from exc

    if answers and all(_blank(answer) for answer in answers):
        # the kit pads even an empty answer (an alignment line, a skeleton), so look at the raw text
        raise H3Error(f"{who} returned an empty answer. {hint}")

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
        raise H3Error(f"{who} returned an empty answer. {hint}")

    return {
        "variant": result["variant"],
        "clips": clips,
        "durations": durations or [options["duration"]],
        "text": join_clips(clips, durations),
        "errors": errors,
        "warnings": warnings,
        "report": format_report(result["variant"], len(clips), errors, warnings),
    }
