from __future__ import annotations

from pathlib import Path

import pandas as pd
from ruamel.yaml import YAML


def test_package_resources_match_declared_schema() -> None:
    """
    Every configured package resource must contain its declared fields and data.
    """
    package = (
        Path(__file__).resolve().parents[1]
        / "data/packages/appg_groups_and_memberships"
    )
    yaml = YAML(typ="safe")
    for name in ("register", "members", "categories"):
        resource = yaml.load((package / f"{name}.resource.yaml").read_text())
        frame = pd.read_parquet(package / resource["path"])
        assert not frame.empty, name
        assert list(frame.columns) == [
            field["name"] for field in resource["schema"]["fields"]
        ], name
