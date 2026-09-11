import glob
import os


def read_first_file(directory, pattern):
    """Read whichever file matches `pattern` in `directory`.

    The exact filename yue2's Plan.save()/Song.save_artifacts() write isn't
    documented anywhere we could confirm - discovering it by glob instead of
    hardcoding a guessed name means a harmless naming difference doesn't
    turn into a silent wrong-file read or a crash.
    """
    matches = sorted(glob.glob(os.path.join(directory, pattern)))
    if not matches:
        raise FileNotFoundError(f"yue2 did not produce a {pattern} file in {directory}")
    with open(matches[0], "r", encoding="utf-8") as f:
        return f.read()


def build_generate_kwargs(style, lyrics, cot, seed, abc=""):
    """Assembles the pipeline() call's kwargs - `abc` is only passed at all
    when non-empty, since yue2's fresh-generation path is triggered by its
    absence, not by an empty string.
    """
    kwargs = {"style": style, "lyrics": lyrics, "cot": cot, "seed": seed}
    if abc:
        kwargs["abc"] = abc
    return kwargs
