"""The generator list, mirroring 52prompts.com's "Generators" menu.

Only the page slug is recorded here, never the prompt data: the word lists are
the site's content and are fetched at run time, exactly like the booru node
fetches images rather than shipping them.

`Field` entries say which node widget feeds which DOM id in the generator's
script - the generators that take character names read `Input1..3`, the ones
that take a list read `choicelist`, and most read nothing at all.
"""

from dataclasses import dataclass, field

PAGE_BASE = "https://52prompts.com/"


@dataclass(frozen=True)
class Field:
    widget: str  # the node widget the user types into
    dom_id: str  # the id the generator's own script reads it back from
    label: str  # what the frontend calls it
    default: str = ""
    multiline: bool = False
    required: bool = False


@dataclass(frozen=True)
class Generator:
    label: str  # the dropdown entry, and what a workflow stores
    slug: str  # 52prompts.com/<slug>/
    fields: tuple = ()
    # ids whose `.selected` reads true while the paired input is blank. The
    # silly-character generator switches between "use my name" and "pick one
    # for me" through a <select> rather than through the text field itself.
    selected_if_blank: dict = field(default_factory=dict)

    @property
    def page_url(self):
        return f"{PAGE_BASE}{self.slug}/"


_NAME_1 = Field("input_1", "Input1", "First character")
_NAME_2 = Field("input_2", "Input2", "Second character")
_NAME_3 = Field("input_3", "Input3", "Third character")

GENERATORS = (
    Generator("Prompts", "random-prompt-generator"),
    Generator("Genres", "random-genre-generator"),
    Generator(
        "Scenarios - Single Person",
        "single-character-scenario-generator",
        fields=(Field("input_1", "Input1", "Character name"),),
    ),
    Generator("Scenarios - Two Person", "random-scenario-generator", fields=(_NAME_1, _NAME_2)),
    Generator(
        "Scenarios - Three Character",
        "three-person-random-scenario-generator",
        fields=(_NAME_1, _NAME_2, _NAME_3),
    ),
    Generator(
        "Scenarios - Cast of Characters",
        "cast-random-scenario-generator",
        fields=(
            Field(
                "choice_list",
                "choicelist",
                "Cast (one name per line)",
                multiline=True,
                required=True,
            ),
        ),
    ),
    Generator("Teen Characters", "random-teen-character-generator"),
    Generator(
        "Objects",
        "random-object-generator",
        fields=(Field("input_1", "Input1", "How many objects", default="1"),),
    ),
    Generator("Locations", "random-location-generator"),
    Generator("Hobbies", "random-hobby-generator"),
    Generator("Monster Characters", "random-monster-character-generator"),
    Generator("Zodiac Signs", "random-zodiac-sign-generator"),
    Generator("Scenes", "random-scene-generator"),
    Generator("Silly Prompts", "random-silly-prompt-generator"),
    Generator("Mermaids", "random-mermaid-generator"),
    Generator(
        "Silly Characters",
        "random-silly-character-generator",
        fields=(Field("input_1", "Input1", "Character name (blank picks one)"),),
        selected_if_blank={"random": "Input1"},
    ),
    Generator("People", "random-person-generator"),
    Generator("Random Questions", "random-question-generator"),
    Generator(
        "Random Choice",
        "random-choice-generator",
        fields=(
            Field("input_1", "Input1", "How many to pick", default="1"),
            Field(
                "choice_list",
                "choicelist",
                "Your options (one per line)",
                multiline=True,
                required=True,
            ),
        ),
    ),
    Generator("Emotions", "random-emotion-generator"),
)

_BY_LABEL = {generator.label: generator for generator in GENERATORS}

GENERATOR_LABELS = [generator.label for generator in GENERATORS]
DEFAULT_GENERATOR = GENERATORS[0].label

# every widget any generator can ask for, in the order the node declares them
WIDGET_NAMES = ("input_1", "input_2", "input_3", "choice_list")


def get_generator(label):
    generator = _BY_LABEL.get(label)
    if generator is None:
        raise KeyError(f"unknown 52prompts generator: {label}")
    return generator


def describe(generator):
    """The generator as the frontend needs it, for showing the right widgets."""
    return {
        "label": generator.label,
        "page_url": generator.page_url,
        "fields": [
            {
                "widget": item.widget,
                "label": item.label,
                "default": item.default,
                "multiline": item.multiline,
                "required": item.required,
            }
            for item in generator.fields
        ],
    }


__all__ = [
    "Field",
    "Generator",
    "GENERATORS",
    "GENERATOR_LABELS",
    "DEFAULT_GENERATOR",
    "WIDGET_NAMES",
    "get_generator",
    "describe",
]
