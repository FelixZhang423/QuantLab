import tempfile
import unittest
from pathlib import Path

import pandas as pd

from custom_bt.data import (
    build_master_store,
    list_store_stocks,
    load_meta,
    load_pool_panel,
    load_store_stock_list,
    prepare_chunk,
    save_store_stock_list,
    update_store,
)


class DataStoreTests(unittest.TestCase):
    def test_prepare_chunk_preserves_pool_metadata_types(self):
        chunk = pd.DataFrame(
            {
                "code": ["1"],
                "timestamps": ["2024-01-02"],
                "open": [10.0],
                "close": [11.0],
                "high": [12.0],
                "low": [9.0],
                "vol": [1000.0],
                "amount": [10000.0],
                "Ifsuspend": [0],
                "category": ["stock"],
                "ListedDate": ["1991-04-03"],
                "ListedSector": ["main"],
            }
        )

        out = prepare_chunk(chunk)

        self.assertEqual(out.loc[0, "category"], "stock")
        self.assertEqual(pd.Timestamp(out.loc[0, "ListedDate"]), pd.Timestamp("1991-04-03"))
        self.assertEqual(out.loc[0, "ListedSector"], "main")
        self.assertEqual(float(out.loc[0, "close"]), 11.0)

    def test_update_store_preserves_new_numeric_fields_in_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "daily.csv"
            store_dir = root / "store"
            pd.DataFrame(
                {
                    "code": ["1", "2"],
                    "timestamps": ["2024-01-02", "2024-01-02"],
                    "open": [10.0, 20.0],
                    "close": [11.0, 21.0],
                    "high": [12.0, 22.0],
                    "low": [9.0, 19.0],
                    "vol": [1000.0, 2000.0],
                    "amount": [10000.0, 40000.0],
                    "my_factor": [0.1, -0.2],
                }
            ).to_csv(csv_path, index=False)

            update_store(csv_path, store_dir, columns=None, chunksize=10)
            meta = load_meta(store_dir)

            self.assertEqual(meta["layout"], "per_stock_parquet")
            self.assertIn("my_factor", meta["fields"])
            self.assertIn({"name": "my_factor", "dtype": "float64"}, meta["field_catalog"])

    def test_build_master_store_and_load_pool_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "daily.csv"
            store_dir = root / "master"
            pd.DataFrame(
                {
                    "code": ["1", "1", "2", "2"],
                    "timestamps": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
                    "open": [10.0, 10.5, 20.0, 20.5],
                    "close": [10.2, 10.7, 20.2, 20.7],
                    "high": [10.3, 10.8, 20.3, 20.8],
                    "low": [9.8, 10.1, 19.8, 20.1],
                    "vol": [1000.0, 1100.0, 2000.0, 2100.0],
                    "amount": [10000.0, 11500.0, 40000.0, 43000.0],
                    "Ifsuspend": [0, 0, 0, 0],
                    "category": ["stock"] * 4,
                    "ListedDate": ["1991-04-03"] * 4,
                    "my_factor": [1.0, 2.0, 3.0, 4.0],
                }
            ).to_csv(csv_path, index=False)

            result = build_master_store(
                csv_path,
                store_dir,
                fields=["my_factor"],
                chunksize=2,
            )
            panel = load_pool_panel(
                store_dir,
                codes=["000002"],
                start_date="2024-01-02",
                end_date="2024-01-02",
            )

            self.assertEqual(result["n_stocks"], 2)
            self.assertEqual(panel["code"].tolist(), ["000002"])
            self.assertEqual(panel["date"].dt.strftime("%Y-%m-%d").tolist(), ["2024-01-02"])
            self.assertEqual(float(panel["my_factor"].iloc[0]), 4.0)
            self.assertTrue((store_dir / "meta.json").exists())

    def test_build_master_store_auto_detects_tab_delimiter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "daily.tsv.csv"
            store_dir = root / "master"
            pd.DataFrame(
                {
                    "code": ["1", "2"],
                    "timestamps": ["2024-01-01", "2024-01-01"],
                    "open": [10.0, 20.0],
                    "close": [10.2, 20.2],
                    "high": [10.3, 20.3],
                    "low": [9.8, 19.8],
                    "vol": [1000.0, 2000.0],
                    "amount": [10000.0, 40000.0],
                    "category": ["stock", "stock"],
                    "ListedDate": ["1991-04-03", "1991-04-03"],
                    "my_factor": [1.0, 2.0],
                }
            ).to_csv(csv_path, sep="\t", index=False)

            result = build_master_store(csv_path, store_dir, fields=["my_factor"], chunksize=2)
            panel = load_pool_panel(store_dir, codes=["000002"])

            self.assertEqual(result["n_stocks"], 2)
            self.assertEqual(panel["code"].tolist(), ["000002"])
            self.assertEqual(float(panel["my_factor"].iloc[0]), 2.0)

    def test_update_store_reports_chunk_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "daily.csv"
            pd.DataFrame(
                {
                    "code": ["1", "2", "1"],
                    "timestamps": ["2024-01-01", "2024-01-01", "2024-01-02"],
                    "open": [10.0, 20.0, 10.5],
                    "close": [10.2, 20.2, 10.7],
                    "high": [10.3, 20.3, 10.8],
                    "low": [9.8, 19.8, 10.1],
                    "vol": [1000.0, 2000.0, 1100.0],
                    "amount": [10000.0, 40000.0, 11500.0],
                }
            ).to_csv(csv_path, index=False)
            progress = []

            from custom_bt.data import update_store

            update_store(
                csv_path,
                root / "store",
                chunksize=2,
                progress_callback=progress.append,
            )

            self.assertGreaterEqual(len(progress), 2)
            self.assertEqual(progress[-1]["stage"], "importing")
            self.assertEqual(progress[-1]["rows_read"], 3)
            self.assertEqual(progress[-1]["stocks_touched"], 2)

    def test_list_store_stocks_summarizes_per_stock_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stock_dir = root / "store" / "stocks"
            stock_dir.mkdir(parents=True)
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2024-01-01", "2024-01-03"]),
                    "code": ["000001", "000001"],
                    "open": [10.0, 11.0],
                    "close": [10.5, 11.5],
                    "volume": [1000.0, 1200.0],
                    "amount": [10500.0, 13800.0],
                }
            ).to_parquet(stock_dir / "000001.parquet", index=False)
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2024-01-02"]),
                    "code": ["000002"],
                    "open": [20.0],
                    "close": [21.0],
                    "volume": [2000.0],
                    "amount": [42000.0],
                }
            ).to_parquet(stock_dir / "000002.parquet", index=False)

            stocks = list_store_stocks(root / "store")

            self.assertEqual([item["code"] for item in stocks], ["000001", "000002"])
            self.assertEqual(stocks[0]["rows"], 2)
            self.assertEqual(stocks[0]["start_date"], "2024-01-01")
            self.assertEqual(stocks[0]["end_date"], "2024-01-03")
            self.assertEqual(stocks[0]["latest_date"], "2024-01-03")
            self.assertEqual(stocks[0]["latest_close"], 11.5)
            self.assertEqual(stocks[1]["latest_amount"], 42000.0)

    def test_save_and_load_store_stock_list_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stock_dir = root / "store" / "stocks"
            stock_dir.mkdir(parents=True)
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2024-01-01"]),
                    "code": ["000001"],
                    "open": [10.0],
                    "close": [10.5],
                    "volume": [1000.0],
                    "amount": [10500.0],
                }
            ).to_parquet(stock_dir / "000001.parquet", index=False)

            result = save_store_stock_list(root / "store")
            cached = load_store_stock_list(root / "store")

            self.assertEqual(result["stocks"], 1)
            self.assertTrue((root / "store" / "stock_list.csv").exists())
            self.assertEqual(cached[0]["code"], "000001")
            self.assertEqual(cached[0]["latest_close"], 10.5)


if __name__ == "__main__":
    unittest.main()
