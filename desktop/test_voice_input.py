"""The Whisper worker's protocol and helpers, without a microphone, numpy or a model."""

import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_input  # noqa: E402


class FakeSegment:
    def __init__(self, end, text):
        self.end, self.text = end, text


class FakeModel:
    def __init__(self, segments):
        self.segments, self.calls = segments, []

    def transcribe(self, audio, **options):
        self.calls.append(options)
        return iter(self.segments), None


class VoiceInputTest(unittest.TestCase):
    def test_emit_writes_one_json_line(self):
        out = io.StringIO()
        with redirect_stdout(out):
            voice_input.emit("partial", text="hello")
            voice_input.emit("recording")
        lines = out.getvalue().splitlines()
        self.assertEqual(
            [json.loads(line) for line in lines], [{"state": "partial", "text": "hello"}, {"state": "recording"}]
        )

    def test_transcribe_drops_empty_segments_and_strips_text(self):
        model = FakeModel([FakeSegment(1.0, "  first "), FakeSegment(1.5, "   "), FakeSegment(2.5, "second")])
        self.assertEqual(voice_input.transcribe(model, b"", beam_size=1), [(1.0, "first"), (2.5, "second")])
        self.assertEqual(model.calls[0]["beam_size"], 1)
        self.assertTrue(model.calls[0]["vad_filter"])
        self.assertFalse(
            model.calls[0]["condition_on_previous_text"], "each pass stands alone, no drift between passes"
        )

    def test_joined(self):
        self.assertEqual(voice_input.joined([(1.0, "a"), (2.0, "b c")]), "a b c")
        self.assertEqual(voice_input.joined([]), "")

    def test_missing_model_is_reported_before_the_microphone_opens(self):
        sounddevice = types.ModuleType("sounddevice")
        sounddevice.InputStream = lambda **_: self.fail("the microphone must not open without a model")
        fakes = {"numpy": types.ModuleType("numpy"), "sounddevice": sounddevice}
        with (
            tempfile.TemporaryDirectory() as empty,
            patch.dict(sys.modules, fakes),
            patch.object(voice_input, "MODEL", Path(empty)),
        ):
            with self.assertRaisesRegex(RuntimeError, "Whisper model is missing"):
                voice_input.main()


if __name__ == "__main__":
    unittest.main()
