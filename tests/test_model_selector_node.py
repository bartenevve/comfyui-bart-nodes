"""The Model Selector node against stand-ins for `comfy`, `folder_paths` and a GGUF loader pack: which ComfyUI loader
gets which file, and what comes out where. No torch, no ComfyUI, no real model."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:  # imported before sys.modules is patched: restoring the patch would unload torch, and a second import of it crashes
    import torch  # noqa: F401
except ImportError:
    pass

from _pack import module  # noqa: E402
from test_model_info import (  # noqa: E402
    FLUX_UNET,
    SDXL_CKPT,
    T5_ENCODER,
    VAE_STANDALONE,
    VISION,
    write_gguf,
    write_safetensors,
)


class Fake:
    """Records the calls of the stand-in loaders."""

    def __init__(self, directory, with_gguf_pack=False):
        self.calls = []
        self.dir = directory
        fake = self

        folder_paths = types.ModuleType("folder_paths")
        mapping = {"checkpoints": ["checkpoints"], "diffusion_models": ["diffusion_models", "unet"], "text_encoders": ["text_encoders"],
                   "vae": ["vae"], "clip_vision": ["clip_vision"], "embeddings": ["embeddings"]}
        folder_paths.get_folder_paths = lambda key: [os.path.join(directory, d) for d in mapping.get(key, [])]
        folder_paths.get_full_path = lambda folder, name, *a, **k: None
        folder_paths.get_full_path_or_raise = lambda folder, name, *a, **k: (_ for _ in ()).throw(FileNotFoundError(name))
        self.folder_paths = folder_paths

        sd = types.ModuleType("comfy.sd")

        class CLIPType:
            STABLE_DIFFUSION = 1
            FLUX = 2
            WAN = 3

        sd.CLIPType = CLIPType
        sd.load_checkpoint_guess_config = lambda path, **kw: (fake.calls.append(("checkpoint", os.path.basename(path), kw)) or ("M", "C", "V", None))
        sd.load_diffusion_model = lambda path, model_options={}: fake.calls.append(("diffusion", os.path.basename(path), model_options)) or "M"
        sd.load_clip = lambda **kw: fake.calls.append(("clip", os.path.basename(kw["ckpt_paths"][0]), kw)) or "C"

        class VAE:
            def __init__(self, sd=None, metadata=None):
                fake.calls.append(("vae", sd, metadata))

            def throw_exception_if_invalid(self):
                fake.calls.append(("vae-valid",))

        sd.VAE = VAE
        utils = types.ModuleType("comfy.utils")
        utils.load_torch_file = lambda path, return_metadata=False: (("SD:" + os.path.basename(path), {"m": 1}) if return_metadata else "SD:" + os.path.basename(path))
        clip_vision = types.ModuleType("comfy.clip_vision")
        clip_vision.load = lambda path: fake.calls.append(("vision", os.path.basename(path))) or ("VISION" if "bad" not in path else None)
        comfy = types.ModuleType("comfy")
        comfy.sd, comfy.utils, comfy.clip_vision = sd, utils, clip_vision

        nodes_module = types.ModuleType("nodes")
        nodes_module.NODE_CLASS_MAPPINGS = {}
        if with_gguf_pack:
            class UnetLoaderGGUF:
                def load_unet(self, unet_name, dequant_dtype=None, patch_dtype=None, patch_on_device=None):
                    path = folder_paths.get_full_path("unet", unet_name)
                    fake.calls.append(("gguf-unet", unet_name.endswith(".gguf"), os.path.basename(path)))
                    return ("GGUF_MODEL",)

            class CLIPLoaderGGUF:
                def load_clip(self, clip_name, type="stable_diffusion"):
                    path = folder_paths.get_full_path("clip", clip_name)
                    fake.calls.append(("gguf-clip", os.path.basename(path), type))
                    return ("GGUF_CLIP",)

            nodes_module.NODE_CLASS_MAPPINGS = {"UnetLoaderGGUF": UnetLoaderGGUF, "CLIPLoaderGGUF": CLIPLoaderGGUF}
        self.modules = {"folder_paths": folder_paths, "comfy": comfy, "comfy.sd": sd, "comfy.utils": utils,
                        "comfy.clip_vision": clip_vision, "nodes": nodes_module}


class TestNode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        put = lambda rel, tensors: write_safetensors(os.path.join(self.dir, *rel.split("/")), tensors)  # noqa: E731
        put("checkpoints/sdxl/model.safetensors", SDXL_CKPT)
        put("checkpoints/flux_in_checkpoints.safetensors", FLUX_UNET)  # a diffusion model in the wrong folder
        put("diffusion_models/flux.safetensors", FLUX_UNET)
        put("text_encoders/t5.safetensors", T5_ENCODER)
        put("vae/ae.safetensors", VAE_STANDALONE)
        put("clip_vision/vision.safetensors", VISION)
        put("clip_vision/bad.safetensors", VISION)
        write_gguf(os.path.join(self.dir, "diffusion_models", "flux-Q4.gguf"), "flux", 15)
        write_gguf(os.path.join(self.dir, "text_encoders", "t5-Q8.gguf"), "t5encoder", 7)
        with open(os.path.join(self.dir, "checkpoints", "mystery.safetensors"), "wb") as handle:
            handle.write(b"\x00" * 16)
        self.install()

    def install(self, with_gguf_pack=False):
        self.fake = Fake(self.dir, with_gguf_pack)
        patcher = mock.patch.dict(sys.modules, self.fake.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.nodes = module("model_selector.nodes")
        self.node = self.nodes.ModelSelector()

    def kinds(self, *calls):
        return [c[0] for c in self.fake.calls if c[0] in calls]

    # ---- what each kind of file gives
    def test_a_checkpoint_gives_model_clip_and_vae(self):
        out = self.node.load("checkpoints::sdxl/model.safetensors")
        self.assertEqual(out, ("M", "C", "V", None, "model"))
        self.assertEqual(self.kinds("checkpoint", "diffusion"), ["checkpoint"])

    def test_a_diffusion_model_gives_only_the_model(self):
        self.assertEqual(self.node.load("diffusion_models::flux.safetensors"), ("M", None, None, None, "flux"))

    def test_a_text_encoder_gives_only_the_clip(self):
        self.assertEqual(self.node.load("text_encoders::t5.safetensors"), (None, "C", None, None, "t5"))

    def test_a_vae_gives_only_the_vae_and_it_is_checked(self):
        out = self.node.load("vae::ae.safetensors")
        self.assertEqual((out[0], out[1], out[3], out[4]), (None, None, None, "ae"))
        self.assertEqual(type(out[2]).__name__, "VAE")
        self.assertIn(("vae-valid",), self.fake.calls)
        self.assertEqual(self.fake.calls[0][1:], ("SD:ae.safetensors", {"m": 1}))  # the metadata goes along

    def test_a_clip_vision_file_gives_the_clip_vision(self):
        self.assertEqual(self.node.load("clip_vision::vision.safetensors"), (None, None, None, "VISION", "vision"))

    def test_the_folder_does_not_matter_the_content_decides(self):
        out = self.node.load("checkpoints::flux_in_checkpoints.safetensors")
        self.assertEqual(out, ("M", None, None, None, "flux_in_checkpoints"))
        self.assertEqual(self.kinds("checkpoint", "diffusion"), ["diffusion"])

    def test_the_name_output_is_the_file_name_without_extension(self):
        self.assertEqual(self.node.load("checkpoints::sdxl/model.safetensors")[4], "model")

    # ---- options
    def test_text_encoder_options(self):
        self.node.load("text_encoders::t5.safetensors", clip_type="flux")
        self.assertEqual(self.fake.calls[-1][2]["clip_type"], 2)
        self.assertEqual(self.fake.calls[-1][2]["model_options"], {})
        self.node.load("text_encoders::t5.safetensors", clip_type="no_such_type")
        self.assertEqual(self.fake.calls[-1][2]["clip_type"], 1)  # the default, as Load CLIP does

    def test_a_text_encoder_can_be_kept_on_the_cpu(self):
        if not self.has_torch():
            self.skipTest("torch is needed")
        self.node.load("text_encoders::t5.safetensors", device="cpu")
        self.assertEqual(set(self.fake.calls[-1][2]["model_options"]), {"load_device", "offload_device"})

    def has_torch(self):
        try:
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def test_the_weight_dtype_reaches_checkpoints_and_diffusion_models(self):
        if not self.has_torch():
            self.skipTest("torch is needed")
        import torch

        self.node.load("diffusion_models::flux.safetensors", weight_dtype="fp8_e4m3fn_fast")
        self.assertEqual(self.fake.calls[-1][2], {"dtype": torch.float8_e4m3fn, "fp8_optimizations": True})
        self.node.load("checkpoints::sdxl/model.safetensors", weight_dtype="fp8_e5m2")
        self.assertEqual(self.fake.calls[-1][2]["model_options"], {"dtype": torch.float8_e5m2})
        self.node.load("checkpoints::sdxl/model.safetensors")
        self.assertEqual(self.fake.calls[-1][2]["model_options"], {})

    def test_the_embeddings_folder_is_passed_to_checkpoints_and_clips(self):
        self.node.load("checkpoints::sdxl/model.safetensors")
        self.assertTrue(self.fake.calls[-1][2]["embedding_directory"][0].endswith("embeddings"))

    # ---- GGUF
    def test_gguf_without_a_loader_pack_says_what_to_install(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.node.load("diffusion_models::flux-Q4.gguf")
        self.assertIn("ComfyUI-GGUF", str(ctx.exception))
        self.assertIn("ComfyUI-SmartModelLoaders-MXD", str(ctx.exception))
        self.assertIn("GGUF", self.nodes.ModelSelector.VALIDATE_INPUTS(model="diffusion_models::flux-Q4.gguf"))

    def test_gguf_through_the_loader_pack_even_from_a_folder_it_does_not_know(self):
        self.install(with_gguf_pack=True)
        out = self.node.load("diffusion_models::flux-Q4.gguf")
        self.assertEqual(out, ("GGUF_MODEL", None, None, None, "flux-Q4"))
        self.assertEqual(self.fake.calls[-1], ("gguf-unet", True, "flux-Q4.gguf"))  # the pack found OUR file
        self.assertTrue(self.nodes.ModelSelector.VALIDATE_INPUTS(model="diffusion_models::flux-Q4.gguf"))

    def test_a_gguf_text_encoder_goes_to_the_clip_loader_with_its_type(self):
        self.install(with_gguf_pack=True)
        out = self.node.load("text_encoders::t5-Q8.gguf", clip_type="flux")
        self.assertEqual(out, (None, "GGUF_CLIP", None, None, "t5-Q8"))
        self.assertEqual(self.fake.calls[-1], ("gguf-clip", "t5-Q8.gguf", "flux"))

    def test_folder_paths_is_put_back_after_a_gguf_load(self):
        self.install(with_gguf_pack=True)
        fp = self.fake.folder_paths
        before = (fp.get_full_path, fp.get_full_path_or_raise)
        self.node.load("diffusion_models::flux-Q4.gguf")
        self.assertEqual((fp.get_full_path, fp.get_full_path_or_raise), before)

        class Failing:
            def load_unet(self, name):
                raise RuntimeError("boom")

        self.fake.modules["nodes"].NODE_CLASS_MAPPINGS = {"UnetLoaderGGUF": Failing}
        with self.assertRaises(RuntimeError):
            self.node.load("diffusion_models::flux-Q4.gguf")
        self.assertEqual((fp.get_full_path, fp.get_full_path_or_raise), before)  # also after a failure

    # ---- errors and validation
    def test_nothing_selected_or_missing(self):
        for value, text in (("", "no model is selected"), ("checkpoints::gone.safetensors", "not found"), ("garbage", "not a model id")):
            with self.assertRaises(RuntimeError) as ctx:
                self.node.load(value)
            self.assertIn(text, str(ctx.exception))
            self.assertIn("Model Selector:", str(ctx.exception))

    def test_any_other_loader_failure_names_the_file_and_the_kind(self):
        import comfy.sd as fake_sd

        def broken(path, model_options={}):
            raise ValueError("Error while deserializing header")

        fake_sd.load_diffusion_model = broken
        with self.assertRaises(RuntimeError) as ctx:
            self.node.load("diffusion_models::flux.safetensors")
        message = str(ctx.exception)
        self.assertIn("Model Selector: could not load flux.safetensors as a diffusion model", message)
        self.assertIn("Error while deserializing header", message)

    def test_the_interrupt_button_is_not_swallowed(self):
        import comfy.sd as fake_sd

        class InterruptProcessingException(Exception):
            pass

        def interrupted(path, model_options={}):
            raise InterruptProcessingException()

        fake_sd.load_diffusion_model = interrupted
        with self.assertRaises(InterruptProcessingException):
            self.node.load("diffusion_models::flux.safetensors")

    def test_a_file_whose_kind_is_unknown_is_explained(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.nodes.load_model(os.path.join(self.dir, "checkpoints", "mystery.safetensors"), "unknown")
        self.assertIn("could not be told", str(ctx.exception))

    def test_an_unreadable_file_falls_back_to_the_kind_of_its_folder(self):
        self.assertEqual(self.node.load("checkpoints::mystery.safetensors")[:3], ("M", "C", "V"))

    def test_a_clip_vision_file_that_is_invalid(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.node.load("clip_vision::bad.safetensors")
        self.assertIn("CLIP vision", str(ctx.exception))

    def test_ids_cannot_leave_the_model_folders(self):
        for bad in ("checkpoints::../../etc/passwd", "checkpoints::/etc/passwd", "vae::..\\x.safetensors"):
            with self.assertRaises(RuntimeError):
                self.node.load(bad)

    def test_validation(self):
        validate = self.nodes.ModelSelector.VALIDATE_INPUTS
        self.assertTrue(validate())
        self.assertTrue(validate(model="vae::ae.safetensors"))
        self.assertIn("not found", validate(model="vae::nope.safetensors"))
        self.assertIn("no model is selected", validate(model=""))

    def test_is_changed_follows_the_file(self):
        changed = self.nodes.ModelSelector.IS_CHANGED
        first = changed("vae::ae.safetensors")
        self.assertEqual(first, changed("vae::ae.safetensors"))
        path = os.path.join(self.dir, "vae", "ae.safetensors")
        stat = os.stat(path)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertNotEqual(first, changed("vae::ae.safetensors"))
        value = changed("vae::gone.safetensors")
        self.assertNotEqual(value, value)  # nan

    def test_the_schema(self):
        spec = self.nodes.ModelSelector.INPUT_TYPES()
        self.assertEqual(list(spec["required"]), ["model"])
        self.assertEqual(list(spec["optional"]), ["weight_dtype", "clip_type", "device"])
        self.assertIn("stable_diffusion", spec["optional"]["clip_type"][0])
        self.assertEqual(self.nodes.ModelSelector.RETURN_TYPES, ("MODEL", "CLIP", "VAE", "CLIP_VISION", "STRING"))
        self.assertEqual(self.nodes.ModelSelector.RETURN_NAMES, ("model", "clip", "vae", "clip_vision", "name"))
        self.assertEqual(self.nodes.ModelSelector.CATEGORY, "Bart's nodes/Model")


if __name__ == "__main__":
    unittest.main()
