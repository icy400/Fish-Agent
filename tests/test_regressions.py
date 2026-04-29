import importlib.util
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"


class RegressionTests(unittest.TestCase):
    def test_update_after_inference_updates_only_requested_file(self):
        sys.path.insert(0, str(SERVER_DIR))
        import database

        with tempfile.TemporaryDirectory() as tmp:
            database.init_db(str(Path(tmp) / "data.db"))
            first_id = database.insert_file(
                original_name="first.wav",
                storage_name="first.wav",
                file_hash="hash-1",
                size_bytes=10,
            )
            second_id = database.insert_file(
                original_name="second.wav",
                storage_name="second.wav",
                file_hash="hash-2",
                size_bytes=20,
            )

            database.update_after_inference(
                file_id=first_id,
                fish_count=7,
                total_segments=11,
                duration=22.0,
                fish_ratio=0.6364,
                feeding_level="high",
                feeding_amount=0.8,
                feeding_message="active",
            )

            first = database.get_file(first_id)
            second = database.get_file(second_id)

        self.assertEqual(first["status"], "analyzed")
        self.assertEqual(first["fish_count"], 7)
        self.assertEqual(second["status"], "uploaded")
        self.assertEqual(second["fish_count"], 0)
        self.assertEqual(second["feeding_message"], None)

    def test_index_escapes_uploaded_filename_before_inner_html(self):
        index_html = (SERVER_DIR / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("function escapeHtml", index_html)
        self.assertIn("escapeHtml(f.original_name)", index_html)
        self.assertNotIn("${f.original_name}</a>", index_html)

    def test_audio_infer_serializes_tflite_interpreter_access(self):
        module = self._load_audio_infer_with_fake_dependencies()
        errors = []

        def run_chunk():
            try:
                module._classify_chunk([0.0] * 44100, module.SAMPLE_RATE)
            except Exception as exc:  # pragma: no cover - assertion reports details
                errors.append(str(exc))

        threads = [threading.Thread(target=run_chunk) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])

    def test_training_and_online_preprocessing_share_filter_implementation(self):
        preprocess = (SERVER_DIR / "scripts" / "preprocess.py").read_text(encoding="utf-8")
        audio_infer = (SERVER_DIR / "scripts" / "audio_infer.py").read_text(encoding="utf-8")

        shared_import = "from audio_features import LOWPASS_CUTOFF, LOWPASS_ORDER, butter_lowpass_filter"
        self.assertIn(shared_import, preprocess)
        self.assertIn(shared_import, audio_infer)
        self.assertNotIn("order=5", preprocess)
        self.assertNotIn("filtfilt", preprocess)

    def _load_audio_infer_with_fake_dependencies(self):
        fake_numpy = types.SimpleNamespace(
            float32="float32",
            argmax=lambda values: max(range(len(values)), key=lambda i: values[i]),
            pad=lambda data, *_args, **_kwargs: data,
            expand_dims=lambda data, axis=0: data,
        )

        class FakeMfcc:
            shape = (13, 128)

            def __getitem__(self, _key):
                return self

            @property
            def T(self):
                return self

            def astype(self, _dtype):
                return self

        fake_librosa = types.SimpleNamespace(
            feature=types.SimpleNamespace(mfcc=lambda **_kwargs: FakeMfcc()),
            load=lambda *_args, **_kwargs: ([0.0] * 44100, 22050),
        )

        class FakeInterpreter:
            def __init__(self, model_path):
                self.current_thread = None
                self.guard = threading.Lock()

            def allocate_tensors(self):
                return None

            def get_input_details(self):
                return [{"index": 0}]

            def get_output_details(self):
                return [{"index": 1}]

            def set_tensor(self, _index, _features):
                thread_id = threading.get_ident()
                with self.guard:
                    if self.current_thread is not None:
                        raise RuntimeError("concurrent interpreter use")
                    self.current_thread = thread_id
                time.sleep(0.02)

            def invoke(self):
                time.sleep(0.02)

            def get_tensor(self, _index):
                thread_id = threading.get_ident()
                with self.guard:
                    if self.current_thread != thread_id:
                        raise RuntimeError("interpreter owner changed")
                    self.current_thread = None
                return [[0.7, 0.3]]

        fake_tensorflow = types.SimpleNamespace(
            lite=types.SimpleNamespace(Interpreter=FakeInterpreter)
        )
        fake_signal = types.SimpleNamespace(
            butter=lambda *_args, **_kwargs: "sos",
            sosfilt=lambda _sos, data: data,
        )
        fake_scipy = types.SimpleNamespace(signal=fake_signal)

        fake_modules = {
            "numpy": fake_numpy,
            "tensorflow": fake_tensorflow,
            "librosa": fake_librosa,
            "scipy": fake_scipy,
            "scipy.signal": fake_signal,
        }
        originals = {name: sys.modules.get(name) for name in fake_modules}
        sys.modules.update(fake_modules)
        sys.path.insert(0, str(SERVER_DIR / "scripts"))

        spec = importlib.util.spec_from_file_location(
            "audio_infer_test_module",
            SERVER_DIR / "scripts" / "audio_infer.py",
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        finally:
            for name, original in originals.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

        return module


if __name__ == "__main__":
    unittest.main()
