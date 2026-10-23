"""A text backend for the kit that runs inside ComfyUI: the CLIP / text-encoder LLM that core's
"Generate Text" node uses (Gemma, Qwen3, ...), instead of an Ollama server.

Pure duck typing (`tokenize`, `generate`, `decode`), so the tests drive it with a fake and nothing
here imports ComfyUI.
"""
import json

# `num_predict` 0 means "the model's default" for Ollama; here a token budget is always needed. The kit's
# answers are 200-400 tokens, a story plan with retries more.
DEFAULT_MAX_LENGTH = 2048
MAX_LENGTH = 32768  # core's own ceiling for the Generate Text node

JSON_ONLY = "\n\nReply with a single JSON object only, no other text, matching this JSON schema:\n"


class ClipError(RuntimeError):
    """The CLIP could not write the text (not a text-generation encoder, out of memory, ...)."""


def _is_interrupt(exc):
    # ComfyUI's "Interrupt" button raises this through the model code; it must reach the executor
    return any(cls.__name__ == "InterruptProcessingException" for cls in type(exc).__mro__)


def flatten(messages, fmt=None):
    """(system prompt, one user prompt) from the kit's chat history.

    The encoder's chat template takes one system and one user turn, so a retry's history (the
    answer, then the validator's complaints) is folded into the user prompt.
    """
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    parts = []
    for index, turn in enumerate(turns):
        if index == 0:
            parts.append(turn["content"])
        elif turn["role"] == "assistant":
            parts.append("Your previous answer:\n" + turn["content"])
        else:
            parts.append(turn["content"])
    user = "\n\n".join(parts)
    if fmt is not None:
        user += JSON_ONLY + json.dumps(fmt)
    return system, user


def split_reasoning(text):
    """The answer without the model's <think> block (core's Generate Text does the same split)."""
    reasoning, closed, answer = text.partition("</think>")
    if closed and reasoning.lstrip().startswith("<think>"):
        return answer.strip()
    return text.strip()


def make_chat(clip):
    """A `chat(messages, model, host, think, ...)` function with ollama_chat's call shape."""
    if not (hasattr(clip, "tokenize") and hasattr(clip, "generate") and hasattr(clip, "decode")):
        raise ClipError(
            "this CLIP cannot generate text: connect a text-LLM encoder (a Qwen or Gemma model loaded with "
            "Load CLIP), the kind the Generate Text node accepts"
        )

    def chat(messages, model=None, host=None, think=False, fmt=None, temperature=0.3, num_ctx=None,
             num_predict=None, timeout=None, seed=None, no_think=False, on_answer=None):
        system, user = flatten(messages, fmt)
        max_length = min(num_predict or DEFAULT_MAX_LENGTH, MAX_LENGTH)
        try:
            tokens = clip.tokenize(user, skip_template=False, min_length=1, thinking=bool(think), system_prompt=system)
            ids = clip.generate(
                tokens,
                do_sample=temperature > 0,
                max_length=max_length,
                temperature=max(temperature, 0.01),
                top_k=64,
                top_p=0.95,
                min_p=0.05,
                repetition_penalty=1.05,
                seed=seed,
            )
            text = clip.decode(ids)
        except Exception as exc:
            if _is_interrupt(exc):
                raise
            if isinstance(exc, TypeError):
                raise ClipError(
                    "this CLIP could not be used to generate text (is it a text-LLM encoder, and is ComfyUI "
                    f"recent enough for the Generate Text node?): {str(exc)[:200]}"
                ) from exc
            raise ClipError(f"the CLIP failed to generate text ({type(exc).__name__}): {str(exc)[:200]}") from exc
        answer = split_reasoning(text)
        if on_answer is not None:
            on_answer(answer)
        return answer

    return chat
