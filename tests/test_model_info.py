import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

info = module("model_selector.model_info")
files = module("model_selector.files")


def write_safetensors(path, tensors, meta=None):
    """A header-only .safetensors: tensors is {name: (dtype, shape)}; the data section is a few zero bytes."""
    header = {name: {"dtype": dtype, "shape": list(shape), "data_offsets": [0, 2]} for name, (dtype, shape) in tensors.items()}
    if meta is not None:
        header["__metadata__"] = meta
    raw = json.dumps(header).encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<Q", len(raw)) + raw + b"\x00\x00")


def write_gguf(path, arch="flux", file_type=15, name="Flux Dev", extra_after=True):
    def string(text):
        data = text.encode()
        return struct.pack("<Q", len(data)) + data

    def kv_string(key, value):
        return string(key) + struct.pack("<I", 8) + string(value)

    def kv_u32(key, value):
        return string(key) + struct.pack("<I", 4) + struct.pack("<I", value)

    body = kv_string("general.architecture", arch) + kv_string("general.name", name) + kv_u32("general.file_type", file_type)
    count = 3
    if extra_after:  # a tokenizer-like array after the general.* keys: must not be needed
        body += string("tokenizer.ggml.tokens") + struct.pack("<I", 9) + struct.pack("<I", 8) + struct.pack("<Q", 2) + string("a") + string("b")
        count += 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 123) + struct.pack("<Q", count) + body)


SDXL_CKPT = {
    "model.diffusion_model.input_blocks.0.0.weight": ("F16", (320, 4, 3, 3)),
    "model.diffusion_model.label_emb.0.0.weight": ("F16", (1280, 2816)),
    "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight": ("F16", (49408, 768)),
    "conditioner.embedders.1.model.token_embedding.weight": ("F16", (49408, 1280)),
    "first_stage_model.decoder.conv_in.weight": ("F16", (512, 4, 3, 3)),
}
SD15_CKPT = {
    "model.diffusion_model.input_blocks.0.0.weight": ("F16", (320, 4, 3, 3)),
    "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight": ("F16", (49408, 768)),
    "first_stage_model.decoder.conv_in.weight": ("F16", (512, 4, 3, 3)),
}
FLUX_UNET = {
    "double_blocks.0.img_attn.qkv.weight": ("BF16", (9216, 3072)),
    "single_blocks.0.linear1.weight": ("BF16", (21504, 3072)),
    "img_in.weight": ("BF16", (3072, 64)),
    "guidance_in.in_layer.weight": ("BF16", (3072, 256)),
}
WAN_UNET = {
    "blocks.0.self_attn.q.weight": ("F8_E4M3", (5120, 5120)),
    "patch_embedding.weight": ("F8_E4M3", (5120, 16, 1, 2, 2)),
    "text_embedding.0.weight": ("BF16", (64, 64)),
    "head.head.weight": ("BF16", (64, 5120)),
}
T5_ENCODER = {
    "encoder.block.0.layer.0.SelfAttention.q.weight": ("F16", (4096, 4096)),
    "shared.weight": ("F16", (32128, 4096)),
}
CLIP_L = {"text_model.encoder.layers.0.self_attn.q_proj.weight": ("F16", (768, 768)), "text_projection.weight": ("F16", (768, 768))}
QWEN_LLM = {"model.layers.0.self_attn.q_proj.weight": ("BF16", (2048, 2048)), "model.embed_tokens.weight": ("BF16", (151936, 2048)),
            "lm_head.weight": ("BF16", (151936, 2048))}
VAE_STANDALONE = {"encoder.conv_in.weight": ("F32", (128, 3, 3, 3)), "decoder.conv_in.weight": ("F32", (512, 4, 3, 3)),
                  "decoder.up_blocks.0.resnets.0.conv1.weight": ("F32", (512, 512, 3, 3)), "quant_conv.weight": ("F32", (8, 8, 1, 1))}
WAN_VAE = {"encoder.conv1.weight": ("F32", (96, 3, 3, 3, 3)), "decoder.conv1.weight": ("F32", (384, 16, 3, 3, 3)),
           "decoder.upsamples.0.residual.0.gamma": ("F32", (384, 1, 1, 1))}
VISION = {"vision_model.embeddings.class_embedding": ("F16", (1280,)), "vision_model.encoder.layers.0.self_attn.q_proj.weight": ("F16", (1280, 1280))}
QWEN_VL = {**QWEN_LLM, "visual.blocks.0.attn.qkv.weight": ("BF16", (3840, 1280))}


class WithFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def inspect(self, tensors, name="m.safetensors", meta=None, key=""):
        write_safetensors(self.path(name), tensors, meta)
        return info.inspect_file(self.path(name), key)


class TestKinds(WithFolder):
    def test_what_each_file_is(self):
        cases = ((SDXL_CKPT, info.CHECKPOINT, "SDXL"), (SD15_CKPT, info.CHECKPOINT, "SD 1.x"), (FLUX_UNET, info.DIFFUSION, "Flux"),
                 (WAN_UNET, info.DIFFUSION, "Wan"), (T5_ENCODER, info.TEXT_ENCODER, "T5 / UMT5"), (CLIP_L, info.TEXT_ENCODER, "CLIP"),
                 (QWEN_LLM, info.TEXT_ENCODER, "LLM (Qwen / Llama / Gemma)"), (VAE_STANDALONE, info.VAE, ""), (WAN_VAE, info.VAE, ""),
                 (VISION, info.CLIP_VISION, ""), (QWEN_VL, info.TEXT_ENCODER, "LLM (Qwen / Llama / Gemma)"))
        for tensors, kind, family in cases:
            result = self.inspect(tensors)
            self.assertEqual((result["kind"], result["family"]), (kind, family), list(tensors)[0])
            self.assertEqual(result["kind_source"], "content")

    def test_the_location_does_not_matter(self):
        # a diffusion model lying in the checkpoints folder, a VAE in the unet folder: the content wins
        self.assertEqual(self.inspect(FLUX_UNET, key="checkpoints")["kind"], info.DIFFUSION)
        self.assertEqual(self.inspect(VAE_STANDALONE, key="unet")["kind"], info.VAE)
        self.assertEqual(self.inspect(SDXL_CKPT, key="vae")["kind"], info.CHECKPOINT)

    def test_a_file_that_says_nothing_falls_back_to_its_folder(self):
        result = self.inspect({"mystery.weight": ("F16", (2, 2))}, key="vae")
        self.assertEqual((result["kind"], result["kind_source"]), (info.VAE, "folder"))
        result = self.inspect({"mystery.weight": ("F16", (2, 2))}, key="")
        self.assertEqual((result["kind"], result["outputs"]), (info.UNKNOWN, []))

    def test_what_each_kind_gives(self):
        self.assertEqual(self.inspect(SDXL_CKPT)["outputs"], ["MODEL", "CLIP", "VAE"])
        self.assertEqual(self.inspect(FLUX_UNET)["outputs"], ["MODEL"])
        self.assertEqual(self.inspect(T5_ENCODER)["outputs"], ["CLIP"])
        self.assertEqual(self.inspect(VAE_STANDALONE)["outputs"], ["VAE"])
        self.assertEqual(self.inspect(VISION)["outputs"], ["CLIP_VISION"])

    def test_a_checkpoint_without_a_vae_is_still_a_checkpoint(self):
        tensors = {**FLUX_UNET, "text_encoders.clip_l.transformer.text_model.encoder.layers.0.weight": ("F16", (768, 768))}
        self.assertEqual(self.inspect(tensors)["kind"], info.CHECKPOINT)


class TestFamilyAndPrecision(WithFolder):
    def test_metadata_wins(self):
        result = self.inspect(FLUX_UNET, meta={"modelspec.architecture": "stable-diffusion-xl-v1-base"})
        self.assertEqual(result["family"], "SDXL")
        self.assertEqual(self.inspect(SDXL_CKPT, meta={"ss_base_model_version": "sdxl_base_v1-0", "ss_sd_model_name": "ponyV6"})["family"], "SDXL")

    def test_the_name_is_the_last_resort(self):
        result = self.inspect({"mystery.weight": ("F16", (2, 2))}, name="my_flux_finetune.safetensors", key="checkpoints")
        self.assertEqual(result["family"], "Flux")
        self.assertEqual(self.inspect({"mystery.weight": ("F16", (2, 2))}, name="swansea.safetensors")["family"], "")

    def test_precision_and_parameters(self):
        result = self.inspect(FLUX_UNET)
        self.assertEqual(result["precision"], "bf16")
        self.assertEqual(result["params"], 9216 * 3072 + 21504 * 3072 + 3072 * 64 + 3072 * 256)
        self.assertEqual(self.inspect(SDXL_CKPT)["precision"], "fp16")
        self.assertEqual(self.inspect(VAE_STANDALONE)["precision"], "fp32")
        self.assertEqual(self.inspect(WAN_UNET)["precision"], "fp8")  # the bf16 part is under 15 %

    def test_mixed_precision_names_the_two_biggest(self):
        tensors = {"a.weight": ("F8_E4M3", (1000, 1000)), "b.weight": ("BF16", (500, 500))}
        self.assertEqual(self.inspect(tensors)["precision"], "fp8 + bf16")

    def test_count_text(self):
        for value, want in ((0, ""), (950, "950"), (12_000, "12K"), (123_456_789, "123M"), (11_900_000_000, "11.9B")):
            self.assertEqual(info.count_text(value), want)

    def test_training_data_and_title_are_listed(self):
        result = self.inspect(SDXL_CKPT, meta={"modelspec.title": "My  Model", "ss_network_dim": "32", "junk": "x"})
        self.assertEqual(result["extras"], {"title": "My Model", "network dim": "32"})


class TestGguf(WithFolder):
    def test_a_diffusion_gguf(self):
        write_gguf(self.path("flux1-dev-Q4_K_M.gguf"), "flux", 15, "Flux Dev")
        result = info.inspect_file(self.path("flux1-dev-Q4_K_M.gguf"), "unet_gguf")
        self.assertEqual((result["kind"], result["family"], result["quant"], result["format"]), (info.DIFFUSION, "Flux", "Q4_K_M", "gguf"))
        self.assertEqual(result["outputs"], ["MODEL"])
        self.assertEqual(result["extras"]["title"], "Flux Dev")
        self.assertEqual(result["tensors"], 123)
        self.assertIn("GGUF loader", result["needs"])

    def test_a_text_encoder_gguf(self):
        write_gguf(self.path("t5xxl.gguf"), "t5encoder", 7, "T5")
        result = info.inspect_file(self.path("t5xxl.gguf"), "")
        self.assertEqual((result["kind"], result["quant"], result["outputs"]), (info.TEXT_ENCODER, "Q8_0", ["CLIP"]))

    def test_the_array_after_the_general_keys_is_not_needed(self):
        write_gguf(self.path("a.gguf"), extra_after=False)
        write_gguf(self.path("b.gguf"), extra_after=True)
        self.assertEqual(info.read_gguf(self.path("a.gguf"))["general.architecture"], info.read_gguf(self.path("b.gguf"))["general.architecture"])

    def test_the_quantisation_falls_back_to_the_file_name(self):
        write_gguf(self.path("wan2.2-Q5_K_S.gguf"), "wan", 999)
        self.assertEqual(info.inspect_file(self.path("wan2.2-Q5_K_S.gguf"))["quant"], "Q5_K_S")

    def test_damaged_files_are_not_a_crash(self):
        for name, content in (("empty.gguf", b""), ("short.gguf", b"GGUF"), ("junk.gguf", b"GGUF" + b"\xff" * 40), ("wrong.gguf", b"XXXX" + b"\x00" * 40)):
            with open(self.path(name), "wb") as handle:
                handle.write(content)
            result = info.inspect_file(self.path(name), "unet_gguf")
            self.assertEqual(result["kind"], info.DIFFUSION)  # from the folder
            self.assertFalse(result["readable"])


class TestOtherFiles(WithFolder):
    def test_pickle_files_are_not_opened(self):
        with open(self.path("old.ckpt"), "wb") as handle:
            handle.write(b"cos\nsystem\n(S'echo hi'\ntR.")
        result = info.inspect_file(self.path("old.ckpt"), "checkpoints")
        self.assertEqual((result["kind"], result["kind_source"], result["format"]), (info.CHECKPOINT, "folder", "ckpt"))
        self.assertIn("not read", result["needs"])

    def test_damaged_safetensors(self):
        for name, content in (("empty.safetensors", b""), ("junk.safetensors", b"\xff" * 64), ("huge.safetensors", struct.pack("<Q", 2 ** 40) + b"{}"),
                              ("list.safetensors", struct.pack("<Q", 2) + b"[]")):
            with open(self.path(name), "wb") as handle:
                handle.write(content)
            self.assertEqual(info.read_safetensors(self.path(name)), ({}, {}), name)
        self.assertEqual(info.read_safetensors(self.path("missing.safetensors")), ({}, {}))

    def test_a_missing_file_has_an_info_anyway(self):
        result = info.inspect_file(self.path("gone.safetensors"), "vae")
        self.assertEqual((result["size"], result["kind"]), (0, info.VAE))

    def test_the_header_is_read_once_per_file_version(self):
        write_safetensors(self.path("a.safetensors"), FLUX_UNET)
        info.cached_info(self.path("a.safetensors"))
        calls = []
        original = info.read_safetensors
        info.read_safetensors = lambda p: calls.append(p) or original(p)
        try:
            info.cached_info(self.path("a.safetensors"))
            self.assertEqual(calls, [])
            write_safetensors(self.path("a.safetensors"), {**FLUX_UNET, "extra.weight": ("BF16", (4, 4))})
            self.assertEqual(info.cached_info(self.path("a.safetensors"))["tensors"], 5)
        finally:
            info.read_safetensors = original


class TestFiles(WithFolder):
    def setUp(self):
        super().setUp()
        for rel in ("checkpoints/sdxl/a.safetensors", "checkpoints/b.ckpt", "diffusion_models/flux/c.gguf", "diffusion_models/.hidden/x.safetensors",
                    "text_encoders/t5.sft", "vae/v.pt", "vae/readme.txt", "vae/.d.safetensors", "checkpoints/notes.json"):
            path = self.path(*rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").close()
        self.roots = [(k, self.path(d)) for k, d in (("checkpoints", "checkpoints"), ("diffusion_models", "diffusion_models"),
                                                      ("text_encoders", "text_encoders"), ("vae", "vae"))]

    def test_every_model_file_of_every_format_in_any_subfolder(self):
        found = files.scan(self.roots)
        self.assertEqual([item["id"] for item in found], [
            "checkpoints::b.ckpt", "diffusion_models::flux/c.gguf", "checkpoints::sdxl/a.safetensors", "text_encoders::t5.sft", "vae::v.pt"])

    def test_hidden_and_foreign_files_are_skipped(self):
        names = [item["rel"] for item in files.scan(self.roots)]
        self.assertNotIn(".hidden/x.safetensors", names)
        self.assertFalse(any(n.endswith((".txt", ".json")) for n in names))

    def test_the_same_directory_under_two_keys_is_scanned_once(self):
        roots = files.collect_roots(lambda key: {"diffusion_models": [self.path("diffusion_models")], "unet": [self.path("diffusion_models")],
                                                 "checkpoints": [self.path("checkpoints"), self.path("nowhere")]}.get(key, []))
        self.assertEqual([k for k, _ in roots], ["checkpoints", "diffusion_models"])

    def test_a_file_reachable_through_two_roots_is_listed_once(self):
        roots = [("checkpoints", self.path("checkpoints")), ("vae", self.path("checkpoints"))]
        ids = [item["id"] for item in files.scan(roots)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith("checkpoints::") for i in ids))

    def test_ids_round_trip(self):
        for item in files.scan(self.roots):
            self.assertEqual(files.resolve(item["id"], self.roots), item["path"])

    def test_resolve_refuses_anything_that_leaves_or_does_not_exist(self):
        for bad in ("checkpoints::../vae/v.pt", "checkpoints::/etc/passwd", "checkpoints::sdxl/../../vae/v.pt", "nokey::a.safetensors",
                    "checkpoints::missing.safetensors", "checkpoints::a.txt", "checkpoints", "::a.ckpt", "checkpoints::a\x00.ckpt", None, 5, "checkpoints::"):
            self.assertIsNone(files.resolve(bad, self.roots), repr(bad))

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlinked_collection_works(self):
        target = tempfile.TemporaryDirectory()
        self.addCleanup(target.cleanup)
        open(os.path.join(target.name, "linked.safetensors"), "wb").close()
        os.symlink(target.name, self.path("checkpoints", "collection"))
        ids = [item["id"] for item in files.scan(self.roots)]
        self.assertIn("checkpoints::collection/linked.safetensors", ids)
        self.assertIsNotNone(files.resolve("checkpoints::collection/linked.safetensors", self.roots))

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlink_loop_does_not_hang(self):
        os.symlink(self.path("checkpoints"), self.path("checkpoints", "sdxl", "loop"))
        self.assertTrue(files.scan(self.roots))

    def test_the_cap(self):
        original = files.MAX_FILES
        files.MAX_FILES = 2
        try:
            self.assertEqual(len(files.scan(self.roots)), 2)
        finally:
            files.MAX_FILES = original


if __name__ == "__main__":
    unittest.main()
