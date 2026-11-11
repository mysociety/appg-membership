from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from mysoc_validator import Popolo
from pydantic import BaseModel
from ruamel.yaml import YAML

from appg_membership.models import APPG, APPGList, Member, Officer, register_dates
from appg_membership.senedd_lifecycle import (
    SENEDD_PARLIAMENTS,
    SeneddMembershipChecker,
    bound_senedd_group,
    is_senedd_member,
    load_senedd_history,
    membership_is_current,
    registration_is_current,
)

package_path = Path("data", "packages", "appg_groups_and_memberships")


# Convert the latest register date string to a datetime.date object
def get_latest_register_date():
    """
    Get the latest register date from models.register_dates
    Converts the string format (YYMMDD) to a date object
    """
    latest_register = register_dates[-1]
    # Parse YYMMDD format to date object
    year = int("20" + latest_register[0:2])  # Convert YY to full year
    month = int(latest_register[2:4])
    day = int(latest_register[4:6])
    return date(year, month, day)


# Use the latest register date dynamically
last_register = get_latest_register_date()


def is_lord(s: str) -> bool:
    """
    Check if the name is a lord.
    """
    lord_words = ["lord", "baroness", "lady", "baron", "the earl", "lord bishop"]
    s = s.lower()
    for word in lord_words:
        if word in s:
            return True
    return False


def officer_type(name: str):
    if is_lord(name):
        return "lord"
    else:
        return "mp"


class ExportValidity(BaseModel):
    """
    Flat validity columns shared by register and membership resources.
    """

    registration_id: str | None = None
    senedd_term: int | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    end_reason: str | None = None
    observed_on: date | None = None


def export_validity(
    group: APPG, member: Member | Officer | None = None
) -> ExportValidity:
    """
    Preserve unknown starts and expose the applicable registration and member bounds.
    """
    registration = group.senedd_registration
    if not registration:
        return ExportValidity()
    validity = member.validity if member else registration
    return ExportValidity(
        registration_id=registration.id,
        senedd_term=registration.term,
        valid_from=validity.valid_from if validity else None,
        valid_until=validity.valid_until if validity else registration.valid_until,
        end_reason=validity.end_reason if validity else registration.end_reason,
        observed_on=validity.observed_on if validity else None,
    )


def write_resource(frame: pd.DataFrame, name: str) -> None:
    """
    Write stable, nullable validity columns even when no current Senedd rows exist.
    """
    frame = frame.astype(object).where(frame.notna(), None)
    frame["senedd_term"] = frame["senedd_term"].astype("Int64")
    frame.to_parquet(package_path / f"{name}.parquet", index=False)


def build_register(
    groups: list[APPG] | None = None,
    as_of: date | None = None,
    history: list[APPG] | None = None,
) -> None:
    """
    Export current registrations and separately retain bounded Senedd history.
    """
    groups = list(APPGList.load_all()) if groups is None else groups
    as_of = as_of or date.today()
    template = APPG(slug="", title="")
    all_frame = pd.concat(
        [
            pd.DataFrame(
                [group.flattened_dict() for group in groups]
                or [template.flattened_dict()]
            ),
            pd.DataFrame(
                [export_validity(group).model_dump() for group in groups]
                or [ExportValidity().model_dump()]
            ),
        ],
        axis=1,
    )
    current_indices = [
        index
        for index, group in enumerate(groups)
        if group.parliament not in SENEDD_PARLIAMENTS
        or registration_is_current(group, as_of)
    ]
    write_resource(all_frame.iloc[current_indices].copy(), "register")
    if history is not None:
        rows = [
            group.flattened_dict() | export_validity(group).model_dump()
            for group in history
            if group.senedd_registration
        ]
        frame = pd.DataFrame(rows, columns=all_frame.columns)
        frame = frame.drop_duplicates(["parliament", "registration_id"], keep="last")
        write_resource(frame, "senedd_register_history")


def membership_rows(
    groups: list[APPG],
    checker: SeneddMembershipChecker,
    as_of: date,
    include_history: bool = False,
) -> pd.DataFrame:
    """
    Construct membership rows, checking continuous Senedd service for current output.
    """
    rows = []
    for group in groups:
        for member in [*group.officers, *group.members_list.members]:
            senedd = group.parliament in SENEDD_PARLIAMENTS
            if not include_history and (
                member.removed
                or (senedd and not membership_is_current(member, group, checker, as_of))
            ):
                continue
            officer = isinstance(member, Officer)
            canon_name = None
            if member.twfy_id:
                try:
                    name = checker.popolo.persons[member.twfy_id].get_main_name()
                    canon_name = name.nice_name() if name else None
                except KeyError:
                    pass
            rows.append(
                {
                    "name": member.name,
                    "officer_role": member.role if officer else None,
                    "twfy_id": member.twfy_id,
                    "mnis_id": member.mnis_id,
                    "canon_name": canon_name,
                    "parliament": str(group.parliament),
                    "appg": group.slug,
                    "is_officer": officer or member.is_officer,
                    "member_type": (
                        ("ms" if is_senedd_member(member) else "other")
                        if senedd
                        else officer_type(member.name)
                        if officer
                        else member.member_type
                    ),
                    "source": "parliament"
                    if officer
                    else group.members_list.source_method,
                    "last_updated": (
                        group.members_list.last_updated
                        if senedd or not officer
                        else last_register
                    ),
                    "url_source": (str(group.source_url) if group.source_url else "")
                    if officer
                    else (
                        str(group.members_list.source_url[0])
                        if group.members_list.source_url
                        else ""
                    ),
                    "removed": member.removed,
                    **export_validity(group, member).model_dump(),
                }
            )
    columns = [
        "name",
        "officer_role",
        "twfy_id",
        "mnis_id",
        "canon_name",
        "parliament",
        "appg",
        "is_officer",
        "member_type",
        "source",
        "last_updated",
        "url_source",
        "removed",
        *ExportValidity.model_fields,
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame["identity"] = frame["twfy_id"].fillna(frame["mnis_id"]).fillna(frame["name"])
    frame["is_not_parliament_source"] = frame["source"] != "parliament"
    keys = ["parliament", "appg", "identity"]
    if include_history:
        keys = ["parliament", "registration_id", "identity", "observed_on"]
        frame = frame.sort_values(
            ["last_updated", "valid_until", "is_not_parliament_source"],
            ascending=[False, False, True],
            na_position="last",
        )
    else:
        frame = frame.sort_values("is_not_parliament_source")
    frame = frame.drop_duplicates(keys, keep="first")
    frame = frame.sort_values(
        ["parliament", "appg", "is_not_parliament_source", "twfy_id"]
    )
    return frame.drop(columns=["identity", "is_not_parliament_source"])


def build_members(
    groups: list[APPG] | None = None,
    checker: SeneddMembershipChecker | None = None,
    as_of: date | None = None,
    history: list[APPG] | None = None,
) -> None:
    """
    Export only current memberships; retain bounded Senedd evidence separately.
    """
    checker = checker or SeneddMembershipChecker(Popolo.from_parlparse())
    groups = list(APPGList.load_all()) if groups is None else groups
    groups = [bound_senedd_group(group, checker) for group in groups]
    as_of = as_of or date.today()
    write_resource(membership_rows(groups, checker, as_of), "members")
    if history is not None:
        bounded = [
            bound_senedd_group(group, checker)
            for group in history
            if group.senedd_registration
        ]
        write_resource(
            membership_rows(bounded, checker, as_of, include_history=True),
            "senedd_members_history",
        )


def build_categories(
    groups: list[APPG] | None = None, as_of: date | None = None
) -> None:
    """
    Export categories for the same current groups as the register.
    """
    groups = list(APPGList.load_all()) if groups is None else groups
    as_of = as_of or date.today()
    rows = [
        {
            "appg_slug": group.slug,
            "category_slug": category.name,
            "category_name": category.value,
        }
        for group in groups
        if group.parliament not in SENEDD_PARLIAMENTS
        or registration_is_current(group, as_of)
        for category in group.categories
    ]
    pd.DataFrame(
        rows, columns=["appg_slug", "category_slug", "category_name"]
    ).to_parquet(
        package_path / "categories.parquet",
        index=False,
    )


def build(as_of: date | None = None) -> None:
    """
    Derive current output and historical references from one consistent data snapshot.
    """
    as_of = as_of or date.today()
    checker = SeneddMembershipChecker(Popolo.from_parlparse())
    groups = [bound_senedd_group(group, checker) for group in APPGList.load_all()]
    archived = load_senedd_history(Path("data"))
    archived.sort(key=lambda group: group.members_list.last_updated or date.min)
    history = [
        bound_senedd_group(group, checker)
        for group in [*archived, *groups]
        if group.parliament in SENEDD_PARLIAMENTS
    ]
    build_register(groups, as_of, history)
    build_members(groups, checker, as_of, history)
    build_categories(groups, as_of)
    describe_senedd_resources()


def describe_senedd_resources() -> None:
    """
    Declare validity types explicitly, including date columns with only null values.

    Rebuilding metadata here preserves these declarations when the dataset command
    subsequently encounters the same file hash. No membership start is fabricated
    merely to give schema inference a non-null example.
    """
    from data_common.dataset.resources import DataResource

    yaml = YAML()
    descriptions = {
        "registration_id": "Senedd registration identity, including term and official body ID; null for other parliaments",
        "senedd_term": "Senedd term number; a registration never carries membership into another term",
        "valid_from": "Known membership or registration start, inclusive; null when unknown",
        "valid_until": "Latest possible end, exclusive; not evidence of continuous membership before this date",
        "end_reason": "Reason for the validity bound: term_ended, left_senedd, no_longer_listed or registration_closed",
        "observed_on": "First dated observation of this membership spell or registration; not its start date",
    }
    types = {
        "registration_id": "string",
        "senedd_term": "integer",
        "valid_from": "date",
        "valid_until": "date",
        "end_reason": "string",
        "observed_on": "date",
    }
    for name in (
        "register",
        "members",
        "senedd_register_history",
        "senedd_members_history",
    ):
        resource_path = package_path / f"{name}.resource.yaml"
        DataResource(package_path / f"{name}.parquet").rebuild_yaml()
        resource = yaml.load(resource_path.read_text())
        if name.startswith("senedd_"):
            base_name = "members" if "members" in name else "register"
            base = yaml.load((package_path / f"{base_name}.resource.yaml").read_text())
            base_fields = {field["name"]: field for field in base["schema"]["fields"]}
            resource["title"] = f"Senedd CPG {base_name} history"
            resource["description"] = (
                "Historical and current Senedd CPG evidence, bounded to its term. "
                "Unknown start and observation dates remain null. "
                "These records do not establish continuous historical membership."
            )
            for field in resource["schema"]["fields"]:
                original = base_fields.get(field["name"], {})
                field["description"] = original.get("description")
                field["type"] = original.get("type", field["type"])
        for field in resource["schema"]["fields"]:
            if field["name"] in descriptions:
                field["description"] = descriptions[field["name"]]
                field["type"] = types[field["name"]]
            elif field["name"] == "last_updated":
                field["description"] = (
                    "Source observation date for Senedd records; UK register date for UK officers"
                )
        with resource_path.open("w") as stream:
            yaml.dump(resource, stream)


if __name__ == "__main__":
    build()
