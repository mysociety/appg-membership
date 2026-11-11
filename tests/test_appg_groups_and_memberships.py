from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
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
    for name in (
        "register",
        "members",
        "categories",
        "senedd_register_history",
        "senedd_members_history",
    ):
        resource = yaml.load((package / f"{name}.resource.yaml").read_text())
        frame = pd.read_parquet(package / resource["path"])
        assert not frame.empty, name
        assert list(frame.columns) == [
            field["name"] for field in resource["schema"]["fields"]
        ], name


def test_senedd_exports_are_current_and_bilingual() -> None:
    """
    Current files exclude the Sixth Senedd and preserve both language representations.
    """
    from datetime import date

    package = (
        Path(__file__).resolve().parents[1]
        / "data/packages/appg_groups_and_memberships"
    )
    for name in ("register", "members"):
        frame = pd.read_parquet(package / f"{name}.parquet")
        senedd = frame[frame["parliament"].isin(["senedd-en", "senedd-cy"])]
        assert set(senedd["senedd_term"]) <= {7}
        keys = ["registration_id"]
        if name == "members":
            keys += ["name", "is_officer"]
            assert senedd["last_updated"].notna().all()
            assert set(senedd[senedd["is_officer"]]["member_type"]) <= {"ms"}
        english = (
            senedd[senedd["parliament"] == "senedd-en"][keys]
            .sort_values(keys)
            .reset_index(drop=True)
        )
        welsh = (
            senedd[senedd["parliament"] == "senedd-cy"][keys]
            .sort_values(keys)
            .reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(english, welsh)
    for name in ("senedd_register_history", "senedd_members_history"):
        frame = pd.read_parquet(package / f"{name}.parquet")
        sixth = frame[frame["senedd_term"] == 6]
        assert not sixth.empty
        assert sixth["valid_until"].notna().all()
        assert (sixth["valid_until"] <= date(2026, 4, 8)).all()


def test_validity_schema_types_remain_explicit_when_dates_are_unknown() -> None:
    """
    Null start dates must still be declared as dates in the dataset contract.
    """
    package = (
        Path(__file__).resolve().parents[1]
        / "data/packages/appg_groups_and_memberships"
    )
    yaml = YAML(typ="safe")
    for name in (
        "register",
        "members",
        "senedd_register_history",
        "senedd_members_history",
    ):
        schema = yaml.load((package / f"{name}.resource.yaml").read_text())["schema"][
            "fields"
        ]
        fields = {field["name"]: field for field in schema}
        for key in ("valid_from", "valid_until", "observed_on"):
            assert fields[key]["type"] == "date"
            assert fields[key]["description"]
        assert fields["senedd_term"]["type"] == "integer"


def test_historical_resources_validate_against_their_published_schema() -> None:
    """
    Historical rows must preserve true nulls and satisfy date and field types.
    """
    from frictionless import validate

    package = (
        Path(__file__).resolve().parents[1]
        / "data/packages/appg_groups_and_memberships"
    )
    for name in ("senedd_register_history", "senedd_members_history"):
        report = validate(package / f"{name}.resource.yaml")
        errors = [error.message for task in report.tasks for error in task.errors[:3]]
        assert report.valid, errors


def test_composite_exports_preserve_senedd_terms_and_date_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Exercise the publication formats against the real nullable Senedd resources.
    """
    import json
    import sqlite3

    from data_common.dataset.resource_management import DataPackage

    package_path = (
        Path(__file__).resolve().parents[1]
        / "data/packages/appg_groups_and_memberships"
    )
    package = DataPackage(package_path)
    monkeypatch.setattr(DataPackage, "build_path", lambda self, version="": tmp_path)

    package.build_composites()

    output = json.loads((tmp_path / f"{package.slug}.json").read_text())
    resources = {resource["name"]: resource for resource in output["resources"]}
    current_members = resources["members"]["data"]
    current = next(row for row in current_members if row["parliament"] == "senedd-en")
    assert current["senedd_term"] == 7
    assert type(current["senedd_term"]) is int
    assert current["observed_on"]
    assert (
        next(row for row in current_members if row["parliament"] == "uk")["senedd_term"]
        == ""
    )
    sixth = [
        row
        for row in resources["senedd_members_history"]["data"]
        if row["senedd_term"] == 6
    ]
    assert sixth
    assert all(
        row["valid_until"] and row["valid_until"] <= "2026-04-08" for row in sixth
    )
    assert (tmp_path / f"{package.slug}.xlsx").is_file()
    with sqlite3.connect(tmp_path / f"{package.slug}.sqlite") as connection:
        assert connection.execute(
            "SELECT DISTINCT senedd_term FROM members WHERE parliament = 'senedd-en'"
        ).fetchall() == [(7,)]
        assert (
            connection.execute(
                "SELECT count(*) FROM members WHERE parliament = 'uk' AND senedd_term IS NULL"
            ).fetchone()[0]
            > 0
        )
