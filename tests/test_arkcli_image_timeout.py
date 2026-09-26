import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import provider


class ImageTimeoutTests(unittest.TestCase):
    def test_timeout_preserves_evidence_and_prevents_second_submission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ref = root / "ref.png"
            ref.write_bytes(b"fixture")
            record = root / "call.json"
            args = dict(project="fixture", episodes=[1], endpoint="ep-fixture",
                        profile="fixture", prompt="fixture", inputs=[ref],
                        output_dir=root / "out", record_path=record)
            error = subprocess.TimeoutExpired("arkcli", 1800,
                                              output=b'{"partial":true}',
                                              stderr="waiting for delivery")
            with patch("rating_gate.require"), patch.object(provider.subprocess, "run", side_effect=error) as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    provider.arkcli_image(**args)
                state = json.loads(record.read_text())
                self.assertEqual(state["status"], "unknown_requires_reconciliation")
                self.assertEqual(state["error_type"], "local_process_timeout")
                self.assertEqual(state["stdout"], '{"partial":true}')
                self.assertEqual(state["stderr"], "waiting for delivery")
                self.assertEqual(run.call_args.kwargs["timeout"], 1800)
                with self.assertRaises(FileExistsError):
                    provider.arkcli_image(**args)
                self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
