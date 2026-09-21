import tempfile
import unittest
from pathlib import Path

import pandas as pd

from custom_bt.data import build_master_store
from custom_bt.pools import create_pool, load_pool_codes, load_pool_manifest


class PoolTests(unittest.TestCase):
    def _build_store(self, root: Path) -> Path:
        csv_path = root / "daily.csv"
        rows = []
        specs = {
            "000001": (100.0, "1990-01-01", 0),
            "000002": (200.0, "1990-01-01", 0),
            "000003": (300.0, "2024-01-01", 0),
        }
        for date in pd.date_range("2024-01-01", periods=2, freq="D"):
            for code, (amount, listed, suspended) in specs.items():
                rows.append(
                    {
                        "code": code,
                        "timestamps": date.strftime("%Y-%m-%d"),
                        "open": 10.0,
                        "close": 10.2,
                        "high": 10.3,
                        "low": 9.8,
                        "vol": 1000.0,
                        "amount": amount,
                        "Ifsuspend": suspended,
                        "category": "stock",
                        "ListedDate": listed,
                    }
                )
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        store_dir = root / "master"
        build_master_store(csv_path, store_dir, fields=[])
        return store_dir

    def test_create_pool_selects_liquid_codes_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_dir = self._build_store(root)

            result = create_pool(
                store_dir=store_dir,
                pools_root=root / "pools",
                name="liquid_2",
                selection_start="2024-01-01",
                selection_end="2024-01-02",
                top_n=2,
                min_listed_days=0,
                min_coverage=1.0,
            )

            self.assertEqual(result["n_stocks"], 2)
            self.assertEqual(load_pool_codes(root / "pools", result["pool_id"]), ["000003", "000002"])
            manifest = load_pool_manifest(root / "pools", result["pool_id"])
            self.assertEqual(manifest["top_n"], 2)
            self.assertEqual(manifest["source_signature"], result["source_signature"])

    def test_create_pool_applies_minimum_listed_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_dir = self._build_store(root)

            result = create_pool(
                store_dir=store_dir,
                pools_root=root / "pools",
                name="mature",
                selection_start="2024-01-01",
                selection_end="2024-01-02",
                top_n=2,
                min_listed_days=1000,
                min_coverage=1.0,
            )

            self.assertEqual(load_pool_codes(root / "pools", result["pool_id"]), ["000002", "000001"])

    def test_create_pool_explains_incomplete_master_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "master" / "_staging" / "import_run").mkdir(parents=True)

            with self.assertRaisesRegex(FileNotFoundError, "import job is still running"):
                create_pool(
                    store_dir=root / "master",
                    pools_root=root / "pools",
                    name="liquid_2",
                    selection_start="2024-01-01",
                    selection_end="2024-01-02",
                )


if __name__ == "__main__":
    unittest.main()
