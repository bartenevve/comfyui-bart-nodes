"""The VoxCPM nodes against a stand-in `voxcpm` package: no model, no network, no GPU."""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
import wave
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

HAS_TORCH = importlib.util.find_spec("torch") is not None


class FakeTTS:
    sample_rate = 48000


class FakeVoxCPM:
    """Records how it was built and called; `generate` returns a 0.5 s tone-less 1-D float32 array."""

    loads = []

    def __init__(self, path, **kwargs):
        self.path = path
        self.load_kwargs = kwargs
        self.tts_model = FakeTTS()
        self.calls = []
        self.reference_exists = []

    @classmethod
    def from_pretrained(cls, path, **kwargs):
        instance = cls(path, **kwargs)
        cls.loads.append(instance)
        return instance

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        for key in ("reference_wav_path", "prompt_wav_path"):
            if key in kwargs:
                with wave.open(kwargs[key], "rb") as handle:  # the file must exist, as a real WAV, while generate runs
                    self.reference_exists.append((key, handle.getframerate(), handle.getnchannels()))
        if kwargs.get("reference_wav_path") and getattr(self, "v1", False):
            raise ValueError("reference_wav_path is only supported with VoxCPM2 models")
        return np.linspace(-0.5, 0.5, 24000, dtype=np.float32)


@unittest.skipUnless(HAS_TORCH, "torch is needed")
class TestNodes(unittest.TestCase):
    def setUp(self):
        import torch

        self.torch = torch
        fake = types.ModuleType("voxcpm")
        fake.VoxCPM = FakeVoxCPM
        FakeVoxCPM.loads = []
        patcher = mock.patch.dict(sys.modules, {"voxcpm": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.nodes = module("voxcpm_tts.nodes")
        self.nodes._MODEL_CACHE.clear()
        self.addCleanup(self.nodes._MODEL_CACHE.clear)
        self.loader = self.nodes.VoxCPMModelLoader()
        self.speaker = self.nodes.VoxCPMGenerate()

    def audio(self, seconds=1.0, rate=22050, channels=2):
        return {"waveform": self.torch.rand(1, channels, int(seconds * rate)) - 0.5, "sample_rate": rate}

    def model(self, **kwargs):
        return self.loader.load("openbmb/VoxCPM2", "auto", **kwargs)[0]

    # ---- loader
    def test_loader_passes_the_options_and_picks_the_device_itself_on_auto(self):
        model = self.loader.load("openbmb/VoxCPM2", "auto", optimize=True, load_denoiser=True, local_files_only=True)[0]
        self.assertEqual(model.path, "openbmb/VoxCPM2")
        self.assertEqual(model.load_kwargs, dict(load_denoiser=True, optimize=True, device=None, local_files_only=True))

    def test_loader_passes_an_explicit_device(self):
        self.assertEqual(self.loader.load("openbmb/VoxCPM1.5", "cpu")[0].load_kwargs["device"], "cpu")

    def test_loader_defaults_are_the_cheap_ones(self):
        kwargs = self.model().load_kwargs
        self.assertFalse(kwargs["optimize"])
        self.assertFalse(kwargs["load_denoiser"])

    def test_a_model_is_loaded_once_per_set_of_options(self):
        first, again = self.model(), self.model()
        self.assertIs(first, again)
        self.assertIsNot(first, self.model(optimize=True))
        self.assertEqual(len(FakeVoxCPM.loads), 2)

    def test_loader_remembers_which_checkpoint_it_is(self):
        self.assertEqual(self.model().bart_model_id, "openbmb/VoxCPM2")

    def test_missing_package_gives_installation_advice(self):
        with mock.patch.dict(sys.modules, {"voxcpm": None}):
            with self.assertRaises(RuntimeError) as ctx:
                self.loader.load("openbmb/VoxCPM2", "auto")
        self.assertIn("pip install voxcpm", str(ctx.exception))

    def test_a_local_checkpoint_is_resolved_inside_models_voxcpm_only(self):
        with tempfile.TemporaryDirectory() as base:
            os.makedirs(os.path.join(base, "mine"))
            open(os.path.join(base, "mine", "config.json"), "w").close()
            with mock.patch.object(self.nodes, "_models_dir", return_value=base):
                self.assertEqual(self.nodes._local_models(), ["local: mine"])
                self.assertEqual(self.loader.load("local: mine", "cpu")[0].path, os.path.join(base, "mine"))
                for bad in ("local: ../x", "local: ", "local: gone", "local: mine/../mine"):
                    with self.assertRaises(RuntimeError):
                        self.loader.load(bad, "cpu")

    def test_input_types_list_the_presets(self):
        models = self.nodes.VoxCPMModelLoader.INPUT_TYPES()["required"]["model"][0]
        self.assertEqual(models[:3], ["openbmb/VoxCPM2", "openbmb/VoxCPM1.5", "openbmb/VoxCPM-0.5B"])

    # ---- generate
    def test_plain_speech(self):
        model = self.model()
        audio, info = self.speaker.generate(model, "Hello there.", 5)
        self.assertEqual(audio["sample_rate"], 48000)
        self.assertEqual(tuple(audio["waveform"].shape), (1, 1, 24000))
        self.assertEqual(audio["waveform"].dtype, self.torch.float32)
        call = model.calls[0]
        self.assertEqual((call["text"], call["seed"]), ("Hello there.", 5))
        self.assertNotIn("reference_wav_path", call)
        self.assertIn("text to speech", info)
        self.assertIn("openbmb/VoxCPM2", info)
        self.assertIn("0.5 s at 48000 Hz", info)

    def test_voice_design_prefixes_the_description(self):
        model = self.model()
        _, info = self.speaker.generate(model, "Welcome!", 1, voice_description="A calm old man")
        self.assertEqual(model.calls[0]["text"], "(A calm old man)Welcome!")
        self.assertIn("voice design", info)

    def test_reference_audio_is_written_as_a_mono_wav_and_removed_afterwards(self):
        model = self.model()
        _, info = self.speaker.generate(model, "Hi", 1, reference_audio=self.audio(rate=22050, channels=2))
        self.assertEqual(model.reference_exists, [("reference_wav_path", 22050, 1)])
        self.assertIn("controllable cloning", info)
        self.assertFalse(os.path.exists(model.calls[0]["reference_wav_path"]))

    def test_prompt_audio_needs_its_transcript(self):
        model = self.model()
        with self.assertRaises(RuntimeError) as ctx:
            self.speaker.generate(model, "Hi", 1, prompt_audio=self.audio())
        self.assertIn("prompt_text", str(ctx.exception))
        self.assertEqual(model.calls, [])

    def test_a_transcript_without_audio_is_refused(self):
        with self.assertRaises(RuntimeError):
            self.speaker.generate(self.model(), "Hi", 1, prompt_text="orphan")

    def test_ultimate_cloning_sends_both_files(self):
        model = self.model()
        _, info = self.speaker.generate(model, "Hi", 1, reference_audio=self.audio(), prompt_audio=self.audio(),
                                        prompt_text="the exact words")
        call = model.calls[0]
        self.assertEqual(call["prompt_text"], "the exact words")
        self.assertEqual(len(model.reference_exists), 2)
        self.assertIn("ultimate cloning", info)

    def test_options_reach_the_model(self):
        model = self.model()
        self.speaker.generate(model, "Hi", 1, cfg_value=3.0, inference_timesteps=20, normalize=True, denoise=True,
                              max_len=1000, retry_badcase=False, retry_badcase_max_times=1,
                              retry_badcase_ratio_threshold=4.0)
        call = model.calls[0]
        self.assertEqual((call["cfg_value"], call["inference_timesteps"], call["max_len"]), (3.0, 20, 1000))
        self.assertEqual((call["normalize"], call["denoise"], call["retry_badcase"]), (True, True, False))
        self.assertEqual((call["retry_badcase_max_times"], call["retry_badcase_ratio_threshold"]), (1, 4.0))

    def test_an_older_model_that_cannot_clone_from_a_reference_says_so(self):
        model = self.model()
        model.v1 = True
        with self.assertRaises(RuntimeError) as ctx:
            self.speaker.generate(model, "Hi", 1, reference_audio=self.audio())
        self.assertIn("only supported with VoxCPM2", str(ctx.exception))

    def test_an_unusable_audio_input_is_named(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.speaker.generate(self.model(), "Hi", 1, reference_audio={"nope": 1})
        self.assertIn("reference_audio", str(ctx.exception))

    def test_bad_options_are_a_clear_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.speaker.generate(self.model(), "Hi", 1, cfg_value=99.0)
        self.assertIn("cfg_value", str(ctx.exception))

    def test_empty_text_is_refused_before_anything_runs(self):
        model = self.model()
        with self.assertRaises(RuntimeError):
            self.speaker.generate(model, "  ", 1)
        self.assertEqual(model.calls, [])

    # ---- validation and schema
    def test_validate_inputs(self):
        validate = self.nodes.VoxCPMGenerate.VALIDATE_INPUTS
        self.assertTrue(validate(text=None))
        self.assertTrue(validate(text="Hello", voice_description="calm"))
        self.assertIn("empty", validate(text="  "))

    def test_input_types_use_the_audio_socket_and_a_controlled_seed(self):
        spec = self.nodes.VoxCPMGenerate.INPUT_TYPES()
        self.assertEqual(spec["optional"]["reference_audio"], ("AUDIO",))
        self.assertEqual(spec["optional"]["prompt_audio"], ("AUDIO",))
        self.assertTrue(spec["required"]["seed"][1]["control_after_generate"])
        self.assertEqual(self.nodes.VoxCPMGenerate.RETURN_TYPES, ("AUDIO", "STRING"))
        self.assertEqual(self.nodes.VoxCPMModelLoader.RETURN_TYPES, ("VOXCPM_MODEL",))


if __name__ == "__main__":
    unittest.main()
