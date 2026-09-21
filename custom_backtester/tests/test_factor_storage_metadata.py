import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from single_factor.evaluator import SingleFactorMetrics
from single_factor.storage import FactorStorage


class FactorStorageMetadataTests(unittest.TestCase):
    def test_record_includes_run_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = FactorStorage(
                Path(tmp),
                metadata={"pool_id": "pool_a", "source_signature": "sig_a"},
            )
            metrics = SingleFactorMetrics(
                expression="$close",
                ic=0.1,
                rank_ic=0.1,
                icir=0.5,
                coverage=1.0,
                score=0.2,
                accepted=True,
                reason=None,
                segments={},
            )

            storage.record(metrics)
            row = json.loads((Path(tmp) / "accepted_factors.jsonl").read_text(encoding="utf-8"))

            self.assertEqual(row["pool_id"], "pool_a")
            self.assertEqual(row["source_signature"], "sig_a")
            self.assertEqual(row["expression"], "$close")

    def test_save_state_retries_after_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = FactorStorage(Path(tmp))
            state_path = Path(tmp) / "run_state.json"
            real_replace = os.replace
            attempts = {"count": 0}

            def flaky_replace(src, dst):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise PermissionError("locked")
                return real_replace(src, dst)

            with patch("single_factor.storage.os.replace", side_effect=flaky_replace), patch(
                "single_factor.storage.time.sleep",
                return_value=None,
            ):
                storage.save_state({"attempts": 3, "accepted_count": 1})

            self.assertEqual(attempts["count"], 2)
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8")),
                {"attempts": 3, "accepted_count": 1},
            )


if __name__ == "__main__":
    unittest.main()
