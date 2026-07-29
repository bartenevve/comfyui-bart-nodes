"""Turn a generator choice into one finished prompt.

Two fetches per generator, both cached: the page, to find out which script it
currently loads, and the script itself. The script URL is version-stamped by
the site's CDN and does change, so it is discovered rather than hard-coded.
"""

import html as html_module
import random
import re
import threading
import time

from . import fetch
from . import jsmini
from .catalog import get_generator

OUTPUT_ELEMENT_ID = "promptDisplay"

# The generators live on the site's CDN as raw .js assets. Pinning the host
# keeps a compromised or rewritten page from pointing us at arbitrary code -
# not that we execute it as real JS, but the interpreter's error messages and
# the user's prompt output are still worth keeping honest.
_SCRIPT_URL = re.compile(r"https://res\.cloudinary\.com/[A-Za-z0-9_/.-]+\.js")

_URL_TTL = 3600.0
_url_cache = {}
_url_lock = threading.Lock()

_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.I)
_BLOCK_END = re.compile(r"</\s*(p|div|li|tr|h[1-6])\s*>", re.I)
_TAG = re.compile(r"<[^>]*>")


class GeneratorError(RuntimeError):
    pass


def find_script_url(page_html):
    """The generator script the page loads."""
    match = _SCRIPT_URL.search(page_html)
    if not match:
        raise GeneratorError("no generator script found on the page")
    return match.group(0)


def script_url_for(generator, ttl=_URL_TTL):
    now = time.monotonic()
    with _url_lock:
        cached = _url_cache.get(generator.slug)
        if cached is not None and now - cached[0] < ttl:
            return cached[1]

    url = find_script_url(fetch.cached_text(generator.page_url))

    with _url_lock:
        _url_cache[generator.slug] = (time.monotonic(), url)
    return url


def html_to_text(markup):
    """Flatten a generator's HTML output into plain text.

    The prompts carry real markup - `<br>` between the fields of a character
    sheet, `<i>` around the odd title - so stripping tags without honoring the
    line breaks would run separate fields together into one line.
    """
    text = _BREAK.sub("\n", markup)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub("", text)
    text = html_module.unescape(text)
    text = text.replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def build_document_state(generator, values):
    """The DOM field values and `.selected` ids the script should see."""
    field_values = {}
    for item in generator.fields:
        raw = values.get(item.widget, "")
        text = raw if isinstance(raw, str) else str(raw)
        # strip() rather than strip("\n") even for the multiline fields: a list
        # of nothing but blank lines is an empty list, not a one-item one
        text = text.strip()
        if not text:
            if item.required:
                raise GeneratorError(f"{generator.label} needs {item.label.lower()}")
            text = item.default
        field_values[item.dom_id] = text

    selected = {
        dom_id
        for dom_id, paired in generator.selected_if_blank.items()
        if not field_values.get(paired, "")
    }
    return field_values, selected


def generate(label, values=None, seed=None, source=None):
    """Produce one prompt from the named generator.

    `source` overrides the fetch, which is what the tests use; leaving it None
    goes to the site. `seed` makes the result reproducible - the same seed,
    generator and inputs give the same prompt for as long as the site's word
    lists stay put.
    """
    generator = get_generator(label)
    field_values, selected = build_document_state(generator, values or {})

    if source is None:
        source = fetch.cached_text(script_url_for(generator), referer=generator.page_url)

    rng = random.Random(seed)
    try:
        markup = jsmini.run_script(
            source,
            values=field_values,
            selected=selected,
            rng=rng,
            output_id=OUTPUT_ELEMENT_ID,
        )
    except jsmini.JSError as exc:
        raise GeneratorError(f"could not run the {generator.label} generator: {exc}") from exc

    text = html_to_text(markup)
    if not text:
        raise GeneratorError(f"the {generator.label} generator produced nothing")
    return text
