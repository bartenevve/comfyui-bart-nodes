import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

metadata = module("lora_selector.metadata")
selection = module("lora_selector.selection")


def write_safetensors(path, meta=None, keys=("lora_unet_down_blocks_0.lora_down.weight",)):
    """A header-only .safetensors file (the data section is a few zero bytes): enough for the header reader."""
    header = {key: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for key in keys}
    if meta is not None:
        header["__metadata__"] = meta
    raw = json.dumps(header).encode()
    with open(path, "wb") as handle:
        handle.write(struct.pack("<Q", len(raw)) + raw + b"\x00\x00")


class WithFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def path(self, name):
        return os.path.join(self.dir, name)


class TestHeader(WithFolder):
    def test_metadata_and_tensor_names(self):
        write_safetensors(self.path("a.safetensors"), {"ss_network_dim": "32"}, keys=("x", "y"))
        meta, keys = metadata.read_header(self.path("a.safetensors"))
        self.assertEqual(meta, {"ss_network_dim": "32"})
        self.assertEqual(sorted(keys), ["x", "y"])

    def test_only_string_metadata_values_are_kept(self):
        write_safetensors(self.path("a.safetensors"), {"a": "1", "b": 2, "c": None})
        self.assertEqual(metadata.read_header(self.path("a.safetensors"))[0], {"a": "1"})

    def test_anything_else_gives_nothing(self):
        for name, content in (("empty.safetensors", b""), ("short.safetensors", b"123"), ("junk.safetensors", b"\xff" * 64),
                              ("huge.safetensors", struct.pack("<Q", 2**40) + b"{}"), ("pickle.pt", b"\x80\x04}"),
                              ("list.safetensors", struct.pack("<Q", 2) + b"[]")):
            with open(self.path(name), "wb") as handle:
                handle.write(content)
            self.assertEqual(metadata.read_header(self.path(name)), ({}, []), name)
        self.assertEqual(metadata.read_header(self.path("missing.safetensors")), ({}, []))

    def test_a_pickle_file_is_never_opened(self):
        with open(self.path("a.ckpt"), "wb") as handle:
            handle.write(b"cos\nsystem\n(S'echo hi'\ntR.")
        self.assertEqual(metadata.read_header(self.path("a.ckpt")), ({}, []))


class TestFamily(unittest.TestCase):
    def test_from_metadata(self):
        cases = (
            ({"modelspec.architecture": "stable-diffusion-xl-v1-base/lora"}, "SDXL"),
            ({"modelspec.architecture": "flux-1-dev/lora"}, "Flux"),
            ({"ss_base_model_version": "sdxl_base_v1-0"}, "SDXL"),
            ({"ss_base_model_version": "sd_v1"}, "SD 1.x"),
            ({"ss_base_model_version": "sd_v2"}, "SD 2.x"),
            ({"ss_v2": "True"}, "SD 2.x"),
            ({"ss_base_model_version": "sdxl_base_v1-0", "ss_sd_model_name": "ponyDiffusionV6XL.safetensors"}, "SDXL (Pony)"),
            ({"modelspec.architecture": "stable-diffusion-3-medium/lora"}, "SD 3"),
        )
        for meta, want in cases:
            self.assertEqual(metadata.detect_family(meta, []), want, meta)

    def test_from_tensor_names_when_there_is_no_metadata(self):
        self.assertEqual(metadata.detect_family({}, ["lora_te2_text_model_x", "lora_unet_a"]), "SDXL")
        self.assertEqual(metadata.detect_family({}, ["lora_unet_double_blocks_0_img_attn"]), "Flux")
        self.assertEqual(metadata.detect_family({}, ["transformer.single_transformer_blocks.0.attn"]), "Flux")
        self.assertEqual(metadata.detect_family({}, ["lora_unet_down_blocks_0_attn"]), "SD 1.x / 2.x")
        self.assertEqual(metadata.detect_family({}, ["whatever"]), "")

    def test_metadata_wins_over_tensor_names(self):
        self.assertEqual(metadata.detect_family({"ss_base_model_version": "sd_v1"}, ["lora_te2_x"]), "SD 1.x")


class TestTags(unittest.TestCase):
    def test_frequent_tags_are_summed_over_datasets_and_ranked(self):
        raw = json.dumps({"10_a": {"cat": 30, "dog": 5, "": 9}, "5_b": {"cat": 10, "bird": 12}})
        self.assertEqual(metadata.frequent_tags({"ss_tag_frequency": raw}, limit=3), ["cat", "bird", "dog"])

    def test_bad_tag_data_is_ignored(self):
        for raw in ("", "{oops", "[]", json.dumps({"a": "b"}), json.dumps({"a": {"x": "many"}})):
            self.assertEqual(metadata.frequent_tags({"ss_tag_frequency": raw}), [], raw)


class TestTrainingInfo(unittest.TestCase):
    def test_only_known_filled_values_are_shown(self):
        info = metadata.training_info({"ss_network_dim": "32", "ss_clip_skip": "None", "ss_epoch": "10", "junk": "x"})
        self.assertEqual(info, {"network dim": "32", "epochs": "10"})


class TestSidecars(WithFolder):
    def test_civitai_info(self):
        with open(self.path("foo.civitai.info"), "w") as handle:
            json.dump({"baseModel": "SDXL 1.0", "name": "v2", "trainedWords": ["foostyle", "  ", "bar"],
                       "model": {"name": "Foo", "type": "LORA"}, "description": "<p>A  <b>nice</b>\nstyle &amp; more</p>",
                       "images": [{"meta": None}, {"meta": {"sampler": "Euler a", "steps": 25, "cfgScale": 6, "prompt": "x"}}]}, handle)
        side = metadata.read_sidecars(self.path("foo.safetensors"))
        self.assertEqual(side["triggers"], ["foostyle", "bar"])
        self.assertEqual(side["triggers_source"], "Civitai")
        self.assertEqual(side["base_model"], "SDXL 1.0")
        self.assertEqual(side["civitai"], {"model": "Foo", "version": "v2", "type": "LORA"})
        self.assertEqual(side["settings"], {"sampler": "Euler a", "steps": "25", "cfg": "6"})
        self.assertEqual(side["description"], "A nice style & more")

    def test_a1111_json(self):
        with open(self.path("foo.json"), "w") as handle:
            json.dump({"activation text": "foo, bar baz", "preferred weight": 0.8, "negative text": "ugly", "sd version": "SDXL",
                       "notes": "use low"}, handle)
        side = metadata.read_sidecars(self.path("foo.safetensors"))
        self.assertEqual(side["triggers"], ["foo", "bar baz"])
        self.assertEqual(side["triggers_source"], "sidecar .json")
        self.assertEqual(side["strength"], 0.8)
        self.assertEqual((side["negative"], side["base_model"], side["description"]), ("ugly", "SDXL", "use low"))

    def test_civitai_triggers_win_over_the_json(self):
        with open(self.path("foo.civitai.info"), "w") as handle:
            json.dump({"trainedWords": ["civ"]}, handle)
        with open(self.path("foo.json"), "w") as handle:
            json.dump({"activation text": "json"}, handle)
        self.assertEqual(metadata.read_sidecars(self.path("foo.safetensors"))["triggers"], ["civ"])

    def test_broken_or_huge_sidecars_are_ignored(self):
        with open(self.path("foo.json"), "w") as handle:
            handle.write("{oops")
        with open(self.path("foo.civitai.info"), "w") as handle:
            handle.write(" " * (metadata.MAX_SIDECAR_BYTES + 1))
        side = metadata.read_sidecars(self.path("foo.safetensors"))
        self.assertEqual((side["triggers"], side["strength"], side["base_model"]), ([], None, ""))

    def test_preview_lookup_order(self):
        for name in ("foo.png", "foo.preview.jpg"):
            open(self.path(name), "wb").close()
        self.assertEqual(metadata.find_preview(self.path("foo.safetensors")), self.path("foo.preview.jpg"))
        os.remove(self.path("foo.preview.jpg"))
        self.assertEqual(metadata.find_preview(self.path("foo.safetensors")), self.path("foo.png"))
        os.remove(self.path("foo.png"))
        self.assertIsNone(metadata.find_preview(self.path("foo.safetensors")))


class TestNotes(WithFolder):
    def test_a_note_round_trips_and_an_empty_one_removes_the_entry(self):
        notes = self.path("notes.json")
        saved = metadata.save_note(notes, "a/b.safetensors", {"triggers": "x, y, x", "strength": "0.7", "text": " hi "})
        self.assertEqual(saved, {"triggers": ["x", "y"], "strength": 0.7, "text": "hi"})
        self.assertEqual(metadata.load_notes(notes)["a/b.safetensors"], saved)
        metadata.save_note(notes, "c.safetensors", {"text": "other"})
        metadata.save_note(notes, "a/b.safetensors", {"triggers": [], "strength": "", "text": ""})
        self.assertEqual(list(metadata.load_notes(notes)), ["c.safetensors"])
        self.assertEqual([f for f in os.listdir(self.dir) if f.endswith(".part")], [])

    def test_bad_notes_are_refused(self):
        for note in ("x", {"strength": "heavy"}, {"strength": 1000}, {"triggers": ["w"] * 51}, {"text": "x" * 3000}, {"triggers": 5}):
            with self.assertRaises(ValueError, msg=str(note)[:30]):
                metadata.clean_note(note)

    def test_missing_or_damaged_notes_file_is_empty(self):
        self.assertEqual(metadata.load_notes(self.path("none.json")), {})
        with open(self.path("bad.json"), "w") as handle:
            handle.write("[1]")
        self.assertEqual(metadata.load_notes(self.path("bad.json")), {})


class TestInfo(WithFolder):
    def make(self, name="style/foo.safetensors", meta=None, keys=None):
        os.makedirs(os.path.dirname(self.path(name)), exist_ok=True)
        write_safetensors(self.path(name), meta, **({"keys": keys} if keys else {}))
        return self.path(name), name

    def test_everything_is_put_together(self):
        path, name = self.make(meta={"ss_base_model_version": "sdxl_base_v1-0", "ss_sd_model_name": "base.safetensors",
                                     "ss_network_dim": "16", "ss_tag_frequency": json.dumps({"d": {"foostyle": 40, "1girl": 30}})})
        with open(os.path.splitext(path)[0] + ".json", "w") as handle:
            json.dump({"activation text": "foostyle", "preferred weight": 0.9}, handle)
        info = metadata.lora_info(path, name)
        self.assertEqual((info["name"], info["file"], info["family"], info["format"]), (name, "foo", "SDXL", "safetensors"))
        self.assertEqual((info["triggers"], info["triggers_source"], info["strength"]), (["foostyle"], "sidecar .json", 0.9))
        self.assertEqual(info["frequent_tags"], ["foostyle", "1girl"])
        self.assertEqual(info["training"]["network dim"], "16")
        self.assertTrue(info["readable"])
        self.assertFalse(info["has_preview"])
        self.assertGreater(info["size"], 0)

    def test_my_notes_override_the_sidecars(self):
        path, name = self.make()
        with open(os.path.splitext(path)[0] + ".json", "w") as handle:
            json.dump({"activation text": "theirs", "preferred weight": 0.5}, handle)
        info = metadata.lora_info(path, name, {name: {"triggers": ["mine"], "strength": 1.2, "text": "n"}})
        self.assertEqual((info["triggers"], info["triggers_source"], info["strength"], info["strength_source"]),
                         (["mine"], "my notes", 1.2, "my notes"))
        self.assertEqual(info["notes"], {"triggers": ["mine"], "strength": 1.2, "text": "n"})

    def test_a_file_without_any_metadata_still_has_an_info(self):
        path, name = self.make("plain.safetensors", keys=("lora_te2_x",))
        info = metadata.lora_info(path, name)
        self.assertEqual((info["family"], info["triggers"], info["training"]), ("SDXL", [], {}))

    def test_a_missing_file_is_not_a_crash(self):
        info = metadata.lora_info(self.path("gone.safetensors"), "gone.safetensors")
        self.assertEqual((info["size"], info["family"]), (0, ""))

    def test_summary_carries_what_the_search_needs(self):
        path, name = self.make(meta={"ss_tag_frequency": json.dumps({"d": {"red hair": 3}})})
        with open(os.path.splitext(path)[0] + ".json", "w") as handle:
            json.dump({"activation text": ", ".join(f"w{i}" for i in range(12))}, handle)
        light = metadata.summary(metadata.lora_info(path, name))
        self.assertEqual(len(light["triggers"]), 12)  # all of them, not a teaser
        self.assertEqual(light["frequent_tags"], ["red hair"])
        self.assertEqual(set(light) >= {"name", "file", "family", "has_preview", "base_model"}, True)

    def test_the_header_is_read_once_per_file_version(self):
        path, name = self.make(meta={"ss_network_dim": "8"})
        metadata.lora_info(path, name)
        calls = []
        original = metadata.read_header
        metadata.read_header = lambda p: calls.append(p) or original(p)
        try:
            metadata.lora_info(path, name)
            self.assertEqual(calls, [])
            write_safetensors(path, {"ss_network_dim": "9"}, keys=("lora_unet_down_blocks_x", "second"))  # a new version
            self.assertEqual(metadata.lora_info(path, name)["training"]["network dim"], "9")
        finally:
            metadata.read_header = original


class TestStack(unittest.TestCase):
    def test_a_stack_round_trips_and_drops_empty_rows(self):
        text = json.dumps([{"name": "a.safetensors", "enabled": True, "strength_model": 0.8},
                           {"name": "", "enabled": True}, {"name": " sub\\b.safetensors ", "enabled": False, "strength_model": "1.5", "strength_clip": 0.5}])
        stack = selection.parse_stack(text)
        self.assertEqual(stack, [{"name": "a.safetensors", "enabled": True, "strength_model": 0.8, "strength_clip": None},
                                 {"name": "sub/b.safetensors", "enabled": False, "strength_model": 1.5, "strength_clip": 0.5}])
        self.assertEqual(selection.parse_stack(selection.serialize_stack(stack)), stack)

    def test_empty_means_no_loras(self):
        for text in ("", "  ", None, "[]"):
            self.assertEqual(selection.parse_stack(text), [])

    def test_bad_stacks_are_named(self):
        for text in ("{oops", "{}", "[1]", json.dumps([{"name": 5}]), json.dumps([{"name": "a\x00"}]),
                     json.dumps([{"name": "a", "strength_model": "x"}]), json.dumps([{"name": "a", "strength_model": 1000}]),
                     json.dumps([{"name": "a", "strength_model": float("inf")}]), json.dumps([{"name": "a", "strength_clip": True}]),
                     json.dumps([{"name": f"n{i}"} for i in range(selection.MAX_LORAS + 1)])):
            with self.assertRaises(selection.StackError, msg=text[:40]):
                selection.parse_stack(text)

    def test_active_rows(self):
        stack = selection.parse_stack(json.dumps([
            {"name": "on", "strength_model": 1}, {"name": "off", "enabled": False}, {"name": "zero", "strength_model": 0},
            {"name": "clip only", "strength_model": 0, "strength_clip": 0.5}, {"name": "neg", "strength_model": -0.5}]))
        self.assertEqual([row["name"] for row in selection.active(stack)], ["on", "clip only", "neg"])

    def test_names_text(self):
        stack = selection.parse_stack(json.dumps([{"name": "style/a.safetensors"}, {"name": "b.v2.safetensors"}, {"name": "x\\c.pt"}]))
        self.assertEqual(selection.names_text(stack), "a, b.v2, c")
        self.assertEqual(selection.names_text([]), "")


if __name__ == "__main__":
    unittest.main()
