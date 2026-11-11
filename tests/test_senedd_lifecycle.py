from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest
from mysoc_validator import Popolo
from pydantic import HttpUrl

from appg_membership import build_data, senedd
from appg_membership.models import APPG, Member, MemberList, Officer, Parliament
from appg_membership.senedd_lifecycle import (
    SENEDD_TERMS,
    SeneddMembershipChecker,
    archive_group,
    bound_senedd_group,
    load_senedd_history,
    membership_is_current,
    registration_is_current,
)
from appg_membership.senedd_migration import migrate_senedd_data
from appg_membership.senedd_models import MembershipValidity, SeneddRegistration

FIXTURES = Path(__file__).parent / "fixtures" / "senedd"
PERSON_ID = "uk.org.publicwhip/person/26170"


def make_popolo(
    spells: list[tuple[str, str]],
    chamber: str = "welsh-parliament",
    party_changes: bool = False,
) -> Popolo:
    """
    Build real Popolo relationships for a person with the specified service spells.
    """
    return Popolo.model_validate(
        {
            "persons": [
                {
                    "id": PERSON_ID,
                    "identifiers": [{"scheme": "senedd", "identifier": "5038"}],
                    "other_names": [
                        {"given_name": "Jayne", "family_name": "Bryant", "note": "Main"}
                    ],
                }
            ],
            "organizations": [
                {"id": chamber, "name": "Chamber", "classification": "chamber"}
            ],
            "posts": [
                {
                    "id": "uk.org.publicwhip/cons/70030",
                    "label": "MS for Newport West",
                    "role": "MS",
                    "organization_id": chamber,
                    "area": {"name": "Newport West"},
                }
            ],
            "memberships": [
                {
                    "id": f"uk.org.publicwhip/member/{70000 + index}",
                    "person_id": PERSON_ID,
                    "post_id": "uk.org.publicwhip/cons/70030",
                    "start_date": start,
                    "end_date": end,
                    "end_reason": "changed_party"
                    if party_changes and index < len(spells) - 1
                    else None,
                }
                for index, (start, end) in enumerate(spells)
            ],
        }
    )


def make_group(term: int = 7, body_id: str = "1040") -> APPG:
    """
    Supply a registered group with both parliamentary and external membership.
    """
    observed_on = date(2026, 7, 21) if term == 7 else date(2026, 2, 20)
    return APPG(
        slug="cancer",
        title="Cancer - Cross Party Group",
        parliament=Parliament.SENEDD_EN,
        source_url=HttpUrl(
            f"https://business.senedd.wales/mgOutsideBodyDetails.aspx?ID={body_id}"
        ),
        senedd_registration=SeneddRegistration(
            body_id=body_id,
            term=term,
            verified=True,
            observed_on=observed_on,
            evidence_url=HttpUrl(
                "https://business.senedd.wales/mgListOutsideBodiesByCategory.aspx"
            ),
        ),
        officers=[
            Officer(
                role="Chair",
                name="Jayne Bryant",
                party="",
                twfy_id=PERSON_ID,
                mnis_id="5038",
                validity=MembershipValidity(observed_on=observed_on),
            )
        ],
        members_list=MemberList(
            source_method="official",
            last_updated=observed_on,
            members=[
                Member(
                    name="Jayne Bryant",
                    member_type="ms",
                    twfy_id=PERSON_ID,
                    validity=MembershipValidity(observed_on=observed_on),
                ),
                Member(name="Charity", member_type="other"),
            ],
        ),
    )


@pytest.mark.parametrize("parliament", [Parliament.SENEDD_EN, Parliament.SENEDD_CY])
def test_term_end_closes_every_member_including_returning_ms(
    parliament: Parliament,
) -> None:
    checker = SeneddMembershipChecker(
        make_popolo(
            [
                ("2021-05-06", "2026-04-08"),
                ("2026-05-08", "9999-12-31"),
            ]
        )
    )
    group = make_group(6, "731")
    group.parliament = parliament
    bounded = bound_senedd_group(group, checker)
    assert registration_is_current(bounded, date(2026, 4, 7))
    assert not registration_is_current(bounded, date(2026, 4, 8))
    for member in [*bounded.officers, *bounded.members_list.members]:
        assert member.validity.valid_until == date(2026, 4, 8)
        assert member.validity.end_reason == "term_ended"
        assert not membership_is_current(member, bounded, checker, date(2026, 11, 11))
    assert group.senedd_registration.valid_until is None


def test_midterm_departure_bounds_officers_and_members() -> None:
    checker = SeneddMembershipChecker(make_popolo([("2026-05-08", "2026-09-01")]))
    group = bound_senedd_group(make_group(), checker)
    for member in [group.officers[0], group.members_list.members[0]]:
        assert member.validity.valid_until == date(2026, 9, 1)
        assert member.validity.end_reason == "left_senedd"
        assert membership_is_current(member, group, checker, date(2026, 8, 31))
        assert not membership_is_current(member, group, checker, date(2026, 9, 1))
    assert membership_is_current(
        group.members_list.members[1], group, checker, date(2026, 9, 1)
    )


def test_later_return_needs_fresh_membership_evidence() -> None:
    checker = SeneddMembershipChecker(
        make_popolo(
            [
                ("2026-05-08", "2026-08-01"),
                ("2026-09-01", "9999-12-31"),
            ]
        )
    )
    group = bound_senedd_group(make_group(), checker)
    assert not membership_is_current(
        group.officers[0], group, checker, date(2026, 10, 1)
    )
    fresh = make_group()
    fresh.officers[0].validity.observed_on = date(2026, 9, 15)
    fresh = bound_senedd_group(fresh, checker)
    assert membership_is_current(fresh.officers[0], fresh, checker, date(2026, 10, 1))


def test_party_change_does_not_end_continuous_service() -> None:
    checker = SeneddMembershipChecker(
        make_popolo(
            [
                ("2026-05-08", "2026-08-01"),
                ("2026-08-02", "9999-12-31"),
            ],
            party_changes=True,
        )
    )
    group = bound_senedd_group(make_group(), checker)
    assert membership_is_current(group.officers[0], group, checker, date(2026, 10, 1))
    assert group.officers[0].validity.valid_until is None


@pytest.mark.parametrize("chamber", ["house-of-commons", "house-of-lords"])
def test_other_chamber_service_cannot_verify_senedd_membership(chamber: str) -> None:
    checker = SeneddMembershipChecker(
        make_popolo([("2026-05-08", "9999-12-31")], chamber)
    )
    group = make_group()
    assert not membership_is_current(
        group.officers[0], group, checker, date(2026, 10, 1)
    )


def test_unverified_or_unknown_registration_is_not_current() -> None:
    group = make_group()
    group.senedd_registration.verified = False
    assert not registration_is_current(group, date(2026, 10, 1))
    group.senedd_registration = None
    assert not registration_is_current(group, date(2026, 10, 1))
    group.senedd_registration = make_group().senedd_registration
    group.senedd_registration.term = 8
    assert not registration_is_current(group, date(2030, 10, 1))


def test_registration_grace_period_and_unknown_starts() -> None:
    group = make_group()
    assert SENEDD_TERMS[7].registration_opens_on == date(2026, 7, 1)
    assert not registration_is_current(group, date(2026, 6, 30))
    assert group.senedd_registration.valid_from is None
    assert group.officers[0].validity.valid_from is None


def test_real_list_and_detail_layouts() -> None:
    entries = senedd.parse_current_cpg_list(
        (FIXTURES / "current-list.html").read_text()
    )
    assert len(entries) == 54
    assert entries[0].body_id == "1047"
    senedd.validate_current_detail((FIXTURES / "current-detail.html").read_text())
    with pytest.raises(ValueError, match="Archived"):
        senedd.validate_current_detail((FIXTURES / "archived-detail.html").read_text())


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<h1>Access denied</h1>",
        '<h2>Current Cross-Party Groups</h2><ul class="mgBulletList"><li>unparsed</li></ul>',
        '<h2>Current Cross-Party Groups</h2><ul class="mgBulletList"><li><a href="changed.aspx?ID=1">Group</a></li></ul>',
    ],
)
def test_failed_list_parsing_never_means_empty(html: str) -> None:
    with pytest.raises(ValueError):
        senedd.parse_current_cpg_list(html)


def test_empty_register_reconciles_but_failed_fetch_does_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = make_group()
    folder = tmp_path / "cpg_senedd_en"
    senedd.save_appg(group, folder)
    path = folder / "cancer.json"
    before = path.read_bytes()
    popolo = make_popolo([("2026-05-08", "9999-12-31")])
    monkeypatch.setattr(senedd.Popolo, "from_parlparse", lambda: popolo)

    def fail_fetch(url: str) -> str:
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(senedd, "fetch_page", fail_fetch)
    with pytest.raises(httpx.ConnectError):
        senedd.download_and_convert_senedd_data(
            tmp_path, date(2026, 11, 11), classify_new_groups=False
        )
    assert path.read_bytes() == before
    assert not load_senedd_history(tmp_path)
    monkeypatch.setattr(
        senedd,
        "fetch_page",
        lambda url: '<h2>Current Cross-Party Groups</h2><ul class="mgBulletList"></ul>',
    )
    senedd.download_and_convert_senedd_data(
        tmp_path, date(2026, 11, 11), classify_new_groups=False
    )
    closed = APPG.model_validate_json(path.read_text())
    assert closed.senedd_registration.valid_until == date(2026, 11, 11)
    assert not registration_is_current(closed, date(2026, 11, 11))
    assert len(load_senedd_history(tmp_path)) == 1


def test_partial_bilingual_scrape_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    senedd.save_appg(make_group(), tmp_path / "cpg_senedd_en")
    before = (tmp_path / "cpg_senedd_en/cancer.json").read_bytes()
    monkeypatch.setattr(senedd.Popolo, "from_parlparse", lambda: make_popolo([]))

    def fetch(url: str) -> str:
        if "ListOutside" in url:
            return '<h2>Current Cross-Party Groups</h2><ul class="mgBulletList"><li><a href="mgOutsideBodyDetails.aspx?ID=1040">Cancer</a></li></ul>'
        if "busnes" in url:
            raise httpx.ConnectError("Welsh fetch failed")
        return (FIXTURES / "current-detail.html").read_text()

    monkeypatch.setattr(senedd, "fetch_page", fetch)
    with pytest.raises(httpx.ConnectError):
        senedd.download_and_convert_senedd_data(
            tmp_path, date(2026, 11, 11), classify_new_groups=False
        )
    assert (tmp_path / "cpg_senedd_en/cancer.json").read_bytes() == before
    assert not load_senedd_history(tmp_path)


def test_missing_members_end_and_retained_evidence_keeps_its_anchor(
    tmp_path: Path,
) -> None:
    checker = SeneddMembershipChecker(make_popolo([("2026-05-08", "9999-12-31")]))
    old = make_group()
    new = make_group()
    new.members_list.members = []
    senedd.reconcile_snapshot(old, new, checker, date(2026, 11, 11), tmp_path)
    historical = load_senedd_history(tmp_path)[0]
    external = historical.members_list.members[1]
    assert external.validity.valid_until == date(2026, 11, 11)
    assert new.officers[0].validity.observed_on == date(2026, 7, 21)


def test_new_registration_does_not_inherit_old_members(tmp_path: Path) -> None:
    checker = SeneddMembershipChecker(
        make_popolo(
            [
                ("2021-05-06", "2026-04-08"),
                ("2026-05-08", "9999-12-31"),
            ]
        )
    )
    old = make_group(6, "731")
    new = make_group()
    new.members_list.members = []
    senedd.reconcile_snapshot(old, new, checker, date(2026, 11, 11), tmp_path)
    assert new.members_list.members == []
    assert new.officers[0].validity.observed_on == date(2026, 7, 21)
    assert load_senedd_history(tmp_path)[0].senedd_registration.term == 6


def test_migration_uses_source_evidence_and_is_idempotent(tmp_path: Path) -> None:
    folder = tmp_path / "cpg_senedd_en"
    for slug, body_id in [("cancer", "731"), ("new", "1040"), ("unknown", "999")]:
        group = make_group(body_id=body_id)
        group.slug = slug
        group.senedd_registration = None
        senedd.save_appg(group, folder)
    archive = '<h1>Cross-Party Groups - Sixth Senedd</h1><a href="mgOutsideBodyDetails.aspx?ID=731">Cancer</a>'
    current = '<h2>Current Cross-Party Groups</h2><ul class="mgBulletList"><li><a href="mgOutsideBodyDetails.aspx?ID=1040">New</a></li></ul>'
    popolo = make_popolo([("2021-05-06", "2026-04-08"), ("2026-05-08", "9999-12-31")])
    result = migrate_senedd_data(tmp_path, popolo, archive, current)
    assert result.sixth == result.seventh == result.unverified == 1
    sixth = APPG.model_validate_json((folder / "cancer.json").read_text())
    assert sixth.senedd_registration.term == 6
    assert sixth.senedd_registration.valid_until == date(2026, 4, 8)
    assert sixth.senedd_registration.observed_on is None
    unknown = APPG.model_validate_json((folder / "unknown.json").read_text())
    assert not registration_is_current(unknown, date(2026, 11, 11))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    migrate_senedd_data(tmp_path, popolo, archive, current)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def test_export_filters_expired_members_keeps_languages_and_real_observation_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = SeneddMembershipChecker(
        make_popolo(
            [
                ("2021-05-06", "2026-04-08"),
                ("2026-05-08", "9999-12-31"),
            ]
        )
    )
    old = make_group(6, "731")
    new = make_group()
    welsh = new.model_copy(deep=True)
    welsh.parliament = Parliament.SENEDD_CY
    groups = [bound_senedd_group(group, checker) for group in [old, new, welsh]]
    monkeypatch.setattr(build_data, "package_path", tmp_path)
    build_data.build_register(groups, date(2026, 11, 11), groups)
    build_data.build_members(groups, checker, date(2026, 11, 11), groups)
    register = pd.read_parquet(tmp_path / "register.parquet")
    members = pd.read_parquet(tmp_path / "members.parquet")
    history = pd.read_parquet(tmp_path / "senedd_members_history.parquet")
    assert len(register) == 2
    assert set(members["senedd_term"]) == {7}
    assert members.groupby("parliament").size().to_dict() == {
        "senedd-cy": 2,
        "senedd-en": 2,
    }
    officers = members[members["is_officer"]]
    assert set(officers["member_type"]) == {"ms"}
    assert set(officers["last_updated"]) == {date(2026, 7, 21)}
    assert set(history[history["senedd_term"] == 6]["valid_until"]) == {
        date(2026, 4, 8)
    }
    assert history["valid_from"].isna().all()


def test_expired_only_and_empty_exports_keep_their_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = SeneddMembershipChecker(make_popolo([("2021-05-06", "2026-04-08")]))
    group = bound_senedd_group(make_group(6, "731"), checker)
    monkeypatch.setattr(build_data, "package_path", tmp_path)
    build_data.build_register([group], date(2026, 11, 11), [group])
    build_data.build_members([group], checker, date(2026, 11, 11), [group])
    for name in ("register", "members"):
        frame = pd.read_parquet(tmp_path / f"{name}.parquet")
        assert frame.empty
        assert "valid_until" in frame.columns
    assert not pd.read_parquet(tmp_path / "senedd_members_history.parquet").empty
    build_data.build_register([], date(2026, 11, 11), [])
    build_data.build_members([], checker, date(2026, 11, 11), [])
    assert pd.read_parquet(tmp_path / "register.parquet").empty


def test_register_error_text_is_not_a_confirmed_empty_register() -> None:
    with pytest.raises(ValueError, match="empty register"):
        senedd.parse_current_cpg_list(
            '<h2>Current Cross-Party Groups</h2><ul class="mgBulletList">An error occurred</ul>'
        )


def test_partial_detail_cannot_erase_a_membership_list() -> None:
    page = (FIXTURES / "current-detail.html").read_text()
    with pytest.raises(ValueError):
        senedd.validate_current_detail(page.replace("</ul>", ""))
    with pytest.raises(ValueError, match="Incomplete"):
        senedd.validate_current_detail(page.replace("<li>", '<li class="changed">'))


def test_adjacent_departure_and_return_still_need_fresh_evidence() -> None:
    checker = SeneddMembershipChecker(
        make_popolo(
            [
                ("2026-05-08", "2026-08-01"),
                ("2026-08-02", "9999-12-31"),
            ]
        )
    )
    group = bound_senedd_group(make_group(), checker)
    assert not membership_is_current(
        group.officers[0], group, checker, date(2026, 10, 1)
    )


def test_migration_invalid_git_revision_changes_no_files(tmp_path: Path) -> None:
    import subprocess

    group = make_group(6, "731")
    group.senedd_registration = None
    folder = tmp_path / "cpg_senedd_en"
    senedd.save_appg(group, folder)
    path = folder / "cancer.json"
    before = path.read_bytes()
    archive = '<h1>Cross-Party Groups - Sixth Senedd</h1><a href="mgOutsideBodyDetails.aspx?ID=731">Cancer</a>'
    current = '<h2>Current Cross-Party Groups</h2><ul class="mgBulletList"></ul>'
    with pytest.raises(subprocess.CalledProcessError):
        migrate_senedd_data(
            tmp_path,
            make_popolo([]),
            archive,
            current,
            "nonexistent-senedd-migration-revision",
        )
    assert path.read_bytes() == before
    assert not load_senedd_history(tmp_path)


def test_unresolved_parliamentary_identities_are_not_treated_as_external_members() -> (
    None
):
    checker = SeneddMembershipChecker(make_popolo([]))
    group = make_group()
    unresolved = Officer(role="Chair", name="Unresolved MS", party="")
    assert not membership_is_current(unresolved, group, checker, date(2026, 11, 11))
    unresolved_member = Member(name="Unknown", member_type="ms")
    assert not membership_is_current(
        unresolved_member, group, checker, date(2026, 11, 11)
    )


def test_approximate_service_dates_cannot_verify_a_current_membership() -> None:
    checker = SeneddMembershipChecker(make_popolo([("2026", "9999-12-31")]))
    group = make_group()
    assert not membership_is_current(
        group.officers[0], group, checker, date(2026, 11, 11)
    )


def test_snapshot_names_show_capture_date_and_deduplicate_across_days(
    tmp_path: Path,
) -> None:
    """
    Date-first filenames distinguish changed evidence while retaining the first capture.
    """
    group = make_group()
    first = archive_group(group, tmp_path, captured_on=date(2026, 11, 11))
    original = first.read_bytes()
    assert first.name.startswith("2026-11-11-")
    assert first.parent.name == "senedd-7-1040"
    assert archive_group(group, tmp_path, captured_on=date(2026, 11, 12)) == first
    assert first.read_bytes() == original
    group.title = "Updated title"
    changed = archive_group(group, tmp_path, captured_on=date(2026, 11, 11))
    assert changed.name.startswith("2026-11-11-")
    assert changed != first
    assert len(load_senedd_history(tmp_path)) == 2


def test_legacy_snapshot_names_remain_readable_without_duplicate_writes(
    tmp_path: Path,
) -> None:
    """
    Existing hash-only evidence remains compatible with readers and archival reruns.
    """
    group = make_group()
    dated = archive_group(group, tmp_path, captured_on=date(2026, 11, 11))
    legacy = dated.with_name(dated.name.removeprefix("2026-11-11-"))
    dated.rename(legacy)
    assert archive_group(group, tmp_path, captured_on=date(2026, 11, 12)) == legacy
    assert len(load_senedd_history(tmp_path)) == 1
