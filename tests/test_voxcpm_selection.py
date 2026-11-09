import os
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("voxcpm_tts.selection")


class TestComposeText(unittest.TestCase):
    def test_plain_text_is_unchanged(self):
        self.assertEqual(selection.compose_text("  Hello there. "), "Hello there.")

    def test_a_description_goes_in_parentheses_in_front(self):
        self.assertEqual(
            selection.compose_text("Hello!", "A young woman, gentle and sweet voice"),
            "(A young woman, gentle and sweet voice)Hello!",
        )

    def test_parentheses_inside_the_description_cannot_end_it_early(self):
        self.assertEqual(selection.compose_text("Hi", "calm (very) voice"), "(calm very voice)Hi")

    def test_a_blank_description_is_no_description(self):
        self.assertEqual(selection.compose_text("Hi", "  \n "), "Hi")

    def test_empty_text_is_refused(self):
        for text in ("", "   ", None):
            with self.assertRaises(selection.InputError):
                selection.compose_text(text, "x")

    def test_length_limits(self):
        with self.assertRaises(selection.InputError):
            selection.compose_text("x" * (selection.MAX_TEXT + 1))
        with self.assertRaises(selection.InputError):
            selection.compose_text("x", "y" * (selection.MAX_DESCRIPTION + 1))
        self.assertTrue(selection.compose_text("x" * selection.MAX_TEXT))


class TestModeName(unittest.TestCase):
    def test_every_combination_has_its_own_name(self):
        names = {
            selection.mode_name(r, p, d) for r in (False, True) for p in (False, True) for d in (False, True)
        }
        self.assertEqual(len(names), 6)  # the style flag only matters for reference-only cloning

    def test_plain(self):
        self.assertEqual(selection.mode_name(False, False, False), "text to speech")
        self.assertEqual(selection.mode_name(False, False, True), "voice design")


class TestCheckPrompt(unittest.TestCase):
    def test_audio_and_transcript_go_together(self):
        selection.check_prompt(True, "the words")
        selection.check_prompt(False, "")
        with self.assertRaises(selection.InputError):
            selection.check_prompt(True, "  ")
        with self.assertRaises(selection.InputError):
            selection.check_prompt(False, "orphan transcript")


class TestBuildKwargs(unittest.TestCase):
    def test_defaults_match_upstream(self):
        kwargs = selection.build_kwargs("hi", 7, {})
        self.assertEqual(kwargs["cfg_value"], 2.0)
        self.assertEqual(kwargs["inference_timesteps"], 10)
        self.assertEqual(kwargs["max_len"], 4096)
        self.assertTrue(kwargs["retry_badcase"])
        self.assertFalse(kwargs["normalize"])
        self.assertEqual(kwargs["seed"], 7)
        self.assertNotIn("reference_wav_path", kwargs)
        self.assertNotIn("prompt_wav_path", kwargs)

    def test_paths_are_passed_only_when_there_is_audio(self):
        kwargs = selection.build_kwargs("hi", 1, {}, "r.wav", "p.wav", " the words ")
        self.assertEqual(kwargs["reference_wav_path"], "r.wav")
        self.assertEqual((kwargs["prompt_wav_path"], kwargs["prompt_text"]), ("p.wav", "the words"))

    def test_options_override_and_none_keeps_the_default(self):
        kwargs = selection.build_kwargs("hi", 1, {"cfg_value": 3.5, "inference_timesteps": None, "normalize": True})
        self.assertEqual((kwargs["cfg_value"], kwargs["inference_timesteps"], kwargs["normalize"]), (3.5, 10, True))

    def test_out_of_range_values_are_named(self):
        for name, value in (("cfg_value", 0.0), ("inference_timesteps", 0), ("max_len", 5), ("retry_badcase_max_times", 99)):
            with self.assertRaises(selection.InputError) as ctx:
                selection.build_kwargs("hi", 1, {name: value})
            self.assertIn(name, str(ctx.exception))

    def test_garbage_is_an_input_error_not_a_crash(self):
        for value in ("abc", float("inf"), [1]):
            with self.assertRaises(selection.InputError):
                selection.build_kwargs("hi", 1, {"cfg_value": value})


class TestAudioHelpers(unittest.TestCase):
    def test_mono_float_takes_the_first_batch_item_and_averages_channels(self):
        waveform = np.stack([np.stack([np.ones(5), np.zeros(5)]), np.full((2, 5), 9.0)])  # [2, 2, 5]
        np.testing.assert_allclose(selection.mono_float(waveform), np.full(5, 0.5))

    def test_mono_float_accepts_lower_ranks(self):
        self.assertEqual(selection.mono_float(np.ones((2, 4))).shape, (4,))
        self.assertEqual(selection.mono_float(np.ones(4)).shape, (4,))

    def test_mono_float_cleans_non_finite_values_and_refuses_silence_of_length_zero(self):
        cleaned = selection.mono_float(np.array([[np.nan, np.inf, -np.inf, 0.25]]))
        np.testing.assert_allclose(cleaned, [0, 0, 0, 0.25])
        with self.assertRaises(selection.InputError):
            selection.mono_float(np.zeros((1, 0)))

    def test_write_wav_round_trips_and_clips(self):
        samples = np.array([0.0, 0.5, -0.5, 2.0, -2.0], dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "x.wav")
            selection.write_wav(path, samples, 24000)
            with wave.open(path, "rb") as handle:
                self.assertEqual((handle.getnchannels(), handle.getsampwidth(), handle.getframerate()), (1, 2, 24000))
                pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        np.testing.assert_allclose(pcm / 32767.0, [0, 0.5, -0.5, 1, -1], atol=1e-4)

    def test_info_line(self):
        line = selection.info_line("openbmb/VoxCPM2", "voice design", 48000, 48000, 3)
        self.assertEqual(line, "voice design | openbmb/VoxCPM2 | 1.0 s at 48000 Hz | seed 3")


if __name__ == "__main__":
    unittest.main()
