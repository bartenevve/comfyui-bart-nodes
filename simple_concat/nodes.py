from comfy_api.latest import io

from .selection import DEFAULT_SEPARATOR, TextError, join_texts


class SimpleConcatenate(io.ComfyNode):
    """Any number of inputs, anything that can be turned into text, joined with one separator."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="BartSimpleConcatenate",
            display_name="Bart's Simple concatenate \U0001f517",
            category="Bart's nodes/Text",
            search_aliases=["concatenate", "concat", "join text", "merge text", "combine text", "text join"],
            description="Joins the connected inputs (text, numbers, ...) into one text. A new input appears as soon as the last one is connected.",
            inputs=[
                io.Autogrow.Input(
                    "texts",
                    template=io.Autogrow.TemplatePrefix(io.AnyType.Input("text"), prefix="text", min=0, max=32),
                    tooltip="Text, numbers or anything else that can be written as text. Empty slots are skipped.",
                ),
                io.String.Input(
                    "separator",
                    default=DEFAULT_SEPARATOR,
                    multiline=False,
                    tooltip="Put between the texts. \\n is a line break, \\t a tab.",
                ),
            ],
            outputs=[io.String.Output(display_name="text")],
        )

    @classmethod
    def execute(cls, texts=None, separator=DEFAULT_SEPARATOR) -> io.NodeOutput:
        try:
            return io.NodeOutput(join_texts(texts or {}, separator))
        except TextError as exc:
            raise RuntimeError(f"Simple concatenate: {exc}") from None
