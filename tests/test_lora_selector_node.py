"""The LoraSelector node against stand-in `comfy` / `folder_paths` modules: what is loaded, in which order and
with which strengths. No torch, no ComfyUI, no real LoRA."""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402


class Model:
    """A stand-in MODEL / CLIP that remembers what was applied to it."""

    def __init__(self, kind, applied=()):
        self.kind, self.applied = kind, list(applied)

    def with_(self, name, strength):
        return Model(self.kind, self.applied + [(name, strength)])


def install(directory, new_api=True):
    """Fake modules; returns (modules dict, calls list)."""
    calls = []

    def get_full_path(folder, name):
        path = os.path.join(directory, name.replace("\\", "/"))
        return path if folder == "loras" and ".." not in name and os.path.isfile(path) else None

    if new_api:
        def load_torch_file(path, safe_load=False, return_metadata=False):
            calls.append(("load", os.path.basename(path), safe_load, return_metadata))
            return ({"file": os.path.basename(path)}, {"meta": os.path.basename(path)}) if return_metadata else {"file": path}

        def load_lora_for_models(model, clip, lora, strength_model, strength_clip, lora_metadata=None):
            calls.append(("apply", lora["file"], strength_model, strength_clip, lora_metadata))
            return (model.with_(lora["file"], strength_model), clip.with_(lora["file"], strength_clip) if clip is not None else None)
    else:
        def load_torch_file(path, safe_load=False):
            calls.append(("load", os.path.basename(path), safe_load, None))
            return {"file": os.path.basename(path)}

        def load_lora_for_models(model, clip, lora, strength_model, strength_clip):
            calls.append(("apply", lora["file"], strength_model, strength_clip, None))
            return (model.with_(lora["file"], strength_model), clip.with_(lora["file"], strength_clip) if clip is not None else None)

    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_full_path = get_full_path
    comfy = types.ModuleType("comfy")
    sd = types.ModuleType("comfy.sd")
    sd.load_lora_for_models = load_lora_for_models
    utils = types.ModuleType("comfy.utils")
    utils.load_torch_file = load_torch_file
    comfy.sd, comfy.utils = sd, utils
    return {"folder_paths": folder_paths, "comfy": comfy, "comfy.sd": sd, "comfy.utils": utils}, calls


class TestNode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name in ("a.safetensors", "sub/b.safetensors", "c.safetensors"):
            path = os.path.join(self.tmp.name, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"x")
        self.start(True)
        self.nodes = module("lora_selector.nodes")
        self.node = self.nodes.LoraSelector()

    def start(self, new_api):
        modules, self.calls = install(self.tmp.name, new_api)
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def stack(self, *rows):
        return json.dumps([{"name": n, "enabled": e, "strength_model": s, **({"strength_clip": c} if c is not None else {})} for n, e, s, c in rows])

    def run_node(self, text, clip=True):
        return self.node.apply(Model("model"), text, Model("clip") if clip else None)

    def test_the_rows_are_applied_in_order_with_their_strengths(self):
        model, clip, names = self.run_node(self.stack(("a.safetensors", True, 0.8, None), ("sub/b.safetensors", True, 1.2, 0.4)))
        self.assertEqual(model.applied, [("a.safetensors", 0.8), ("b.safetensors", 1.2)])
        self.assertEqual(clip.applied, [("a.safetensors", 0.8), ("b.safetensors", 0.4)])  # None = the model strength
        self.assertEqual(names, "a, b")

    def test_switched_off_and_zero_rows_are_not_even_loaded(self):
        text = self.stack(("a.safetensors", False, 1, None), ("c.safetensors", True, 0, 0), ("sub/b.safetensors", True, 1, None))
        _, _, names = self.run_node(text)
        self.assertEqual([c for c in self.calls if c[0] == "load"], [("load", "b.safetensors", True, True)])
        self.assertEqual(names, "b")

    def test_without_a_clip_the_clip_strength_is_zero_and_the_clip_output_is_nothing(self):
        model, clip, _ = self.run_node(self.stack(("a.safetensors", True, 0.8, 5.0)), clip=False)
        self.assertIsNone(clip)
        self.assertEqual(model.applied, [("a.safetensors", 0.8)])
        self.assertEqual(self.calls[-1][2:4], (0.8, 0.0))

    def test_an_empty_stack_passes_everything_through(self):
        model, clip, names = self.run_node("[]")
        self.assertEqual((model.applied, clip.applied, names), ([], [], ""))
        self.assertEqual(self.calls, [])

    def test_loading_is_safe_and_the_metadata_goes_along(self):
        self.run_node(self.stack(("a.safetensors", True, 1, None)))
        self.assertEqual(self.calls[0], ("load", "a.safetensors", True, True))
        self.assertEqual(self.calls[1][4], {"meta": "a.safetensors"})

    def test_an_older_comfyui_without_those_arguments_still_works(self):
        self.start(False)
        model, _, names = self.run_node(self.stack(("a.safetensors", True, 1, None)))
        self.assertEqual((model.applied, names), ([("a.safetensors", 1.0)], "a"))

    def test_a_missing_file_is_a_clear_error_that_names_it(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.run_node(self.stack(("gone.safetensors", True, 1, None)))
        self.assertIn("gone.safetensors", str(ctx.exception))
        self.assertIn("Switch the row off", str(ctx.exception))

    def test_a_missing_file_that_is_switched_off_is_ignored(self):
        _, _, names = self.run_node(self.stack(("gone.safetensors", False, 1, None), ("a.safetensors", True, 1, None)))
        self.assertEqual(names, "a")

    def test_a_broken_stack_is_a_runtime_error(self):
        with self.assertRaises(RuntimeError):
            self.run_node("{oops")

    def test_a_name_that_leaves_the_folder_is_not_found(self):
        with self.assertRaises(RuntimeError):
            self.run_node(self.stack(("../etc/passwd", True, 1, None)))

    def test_validation_names_the_problem_at_queue_time(self):
        validate = self.nodes.LoraSelector.VALIDATE_INPUTS
        self.assertTrue(validate())
        self.assertTrue(validate(loras="[]"))
        self.assertTrue(validate(loras=self.stack(("a.safetensors", True, 1, None), ("gone", False, 1, None))))
        self.assertIn("gone.safetensors", validate(loras=self.stack(("gone.safetensors", True, 1, None))))
        self.assertIn("not valid JSON", validate(loras="{"))
        self.assertIn("between", validate(loras=json.dumps([{"name": "a.safetensors", "strength_model": 999}])))

    def test_is_changed_follows_the_files(self):
        changed = self.nodes.LoraSelector.IS_CHANGED
        text = self.stack(("a.safetensors", True, 1, None))
        first = changed(text)
        self.assertEqual(first, changed(text))
        self.assertNotEqual(first, changed(self.stack(("a.safetensors", True, 0.5, None))))
        path = os.path.join(self.tmp.name, "a.safetensors")
        stat = os.stat(path)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertNotEqual(first, changed(text))
        for bad in ("{", self.stack(("gone.safetensors", True, 1, None))):
            value = changed(bad)
            self.assertNotEqual(value, value)  # nan: run it, the error is reported there

    def test_a_switched_off_file_does_not_make_it_rerun(self):
        changed = self.nodes.LoraSelector.IS_CHANGED
        text = self.stack(("a.safetensors", False, 1, None))
        path = os.path.join(self.tmp.name, "a.safetensors")
        before = changed(text)
        stat = os.stat(path)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertEqual(before, changed(text))

    def test_the_schema(self):
        spec = self.nodes.LoraSelector.INPUT_TYPES()
        self.assertEqual(list(spec["required"]), ["model", "loras"])
        self.assertEqual(spec["optional"]["clip"][0], "CLIP")
        self.assertEqual(self.nodes.LoraSelector.RETURN_TYPES, ("MODEL", "CLIP", "STRING"))
        self.assertEqual(self.nodes.LoraSelector.RETURN_NAMES, ("model", "clip", "lora_names"))
        self.assertEqual(self.nodes.LoraSelector.CATEGORY, "Bart's nodes/Model")


if __name__ == "__main__":
    unittest.main()
