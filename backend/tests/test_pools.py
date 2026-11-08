"""Company source pool selection and persistent identity."""
import pytest
from custom_bt.pools import create_pool_from_company
from repositories.pool_store import load_pool_codes, load_pool_manifest
from repositories.clickhouse import LiveDBSettings


class SelectionClient:
    def __init__(self):
        self.sqls = []
    def query(self, sql):
        self.sqls.append(sql)
        if "AS days" in sql:
            return [{"days":2}]
        return [{"code":"1","valid_rows":2,"avg_amount":100},
                {"code":"2","valid_rows":2,"avg_amount":200},
                {"code":"3","valid_rows":1,"avg_amount":300}]


def create(root, client, **options):
    return create_pool_from_company(root, "liquid", "2024-01-01", "2024-01-02",
                                    client=client, settings=LiveDBSettings(), **options)


def test_company_pool_filters_coverage_and_ranks_liquidity(tmp_path):
    client = SelectionClient()
    result = create(tmp_path, client, top_n=2, min_coverage=1)
    assert load_pool_codes(tmp_path,result["pool_id"]) == ["000002","000001"]
    assert load_pool_manifest(tmp_path,result["pool_id"])["data_source"] == "clickhouse"
    assert len(client.sqls) == 2
    assert not (tmp_path / "master").exists()


def test_pool_minimum_listing_days_is_in_company_query(tmp_path):
    client = SelectionClient()
    create(tmp_path,client,top_n=1,min_listed_days=1000)
    assert "1000" in client.sqls[-1]


def test_strict_top_n_rejects_underfilled_pool(tmp_path):
    with pytest.raises(ValueError,match="only 2"):
        create(tmp_path,SelectionClient(),top_n=3,min_coverage=1)


def test_same_selection_preserves_identity_and_requires_explicit_overwrite(tmp_path):
    first = create(tmp_path,SelectionClient(),top_n=2)
    with pytest.raises(FileExistsError):
        create(tmp_path,SelectionClient(),top_n=2)
    second = create(tmp_path,SelectionClient(),top_n=2,overwrite=True)
    assert first["pool_id"] == second["pool_id"]


@pytest.mark.parametrize("options", [{"top_n":0},{"min_coverage":1.1},{"min_listed_days":-1}])
def test_invalid_rules_rejected_before_query(tmp_path,options):
    client = SelectionClient()
    with pytest.raises(ValueError):
        create(tmp_path,client,**options)
    assert not client.sqls
