from __future__ import annotations

from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

import pytest
from mysoc_validator_fast import Person, Popolo

from appg_membership import add_person_ids
from appg_membership.models import (
    APPG,
    Member,
    MemberList,
    NameCorrection,
    NameCorrectionList,
    Officer,
)


class Candidate(NamedTuple):
    identifier: str | None
    end_date: str | None


@pytest.mark.parametrize(
    ("earlier", "later", "winner"),
    [
        (Candidate(None, "2026-01-01"), Candidate("123", "2024-01-01"), 1),
        (Candidate("123", "2024-01-01"), Candidate(None, "2026-01-01"), 0),
        (Candidate("123", "2024-01-01"), Candidate("456", "9999-12-31"), 1),
        (Candidate("123", "9999-12-31"), Candidate("456", "2024-01-01"), 0),
        (Candidate(None, None), Candidate(None, "2024-01-01"), 1),
        (Candidate(None, "2024-01-01"), Candidate(None, None), 0),
        (Candidate(None, None), Candidate(None, None), 0),
        (Candidate(None, "2024"), Candidate(None, "2026-11"), 1),
    ],
)
def test_fast_validator_matching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    earlier: Candidate,
    later: Candidate,
    winner: int,
) -> None:
    """
    Exercise identifier preference, date comparisons and saved IDs with real Rust models.
    """
    monkeypatch.chdir(tmp_path)
    candidates = [earlier, later]
    person_ids = [f"uk.org.publicwhip/person/{10000 + i}" for i in range(2)]
    popolo = Popolo.model_validate(
        {
            "persons": [
                {
                    "id": person_id,
                    "identifiers": [
                        {"scheme": "datadotparl_id", "identifier": candidate.identifier}
                    ]
                    if candidate.identifier
                    else [],
                    "other_names": [
                        {
                            "given_name": "Jane",
                            "family_name": "Example",
                            "note": "Main",
                        }
                    ],
                }
                for person_id, candidate in zip(person_ids, candidates)
            ]
            + [
                {
                    "id": "uk.org.publicwhip/person/99999",
                    "redirect": person_ids[0],
                }
            ],
            "organizations": [
                {
                    "id": "house-of-commons",
                    "name": "House of Commons",
                    "classification": "chamber",
                }
            ],
            "posts": [],
            "memberships": [
                {
                    "id": f"uk.org.publicwhip/member/{10000 + i}",
                    "person_id": person_ids[i],
                    "organization_id": "house-of-commons",
                    "start_date": "2020-01-01",
                    "end_date": candidate.end_date,
                }
                for i, candidate in enumerate(candidates)
                if candidate.end_date
            ],
        }
    )
    monkeypatch.setattr(Popolo, "from_parlparse", lambda: popolo)
    monkeypatch.setattr(add_person_ids, "ineligible_person_ids", [person_ids[winner]])
    NameCorrectionList(
        root=[NameCorrection(original="jane typo", canon="Jane Example")]
    ).save()
    APPG(
        slug="example",
        title="Example",
        officers=[Officer(name="Dr Jane Example MP", role="Chair", party="")],
        members_list=MemberList(
            members=[
                Member(name="Jane Typo", member_type="mp"),
                Member(name="Unknown MP", member_type="mp"),
                Member(name="Lord Unknown", member_type="lord"),
            ]
        ),
    ).save()

    add_person_ids.add_person_ids()

    saved = APPG.load("example")
    for person in [saved.officers[0], saved.members_list.members[0]]:
        assert person.twfy_id == person_ids[winner]
        assert person.mnis_id == str(candidates[winner].identifier)
        assert person.removed is True
    assert saved.members_list.members[1].twfy_id is None
    assert saved.members_list.members[2].twfy_id is None
    assert {item.original for item in NameCorrectionList.load()} == {
        "jane typo",
        "unknown",
    }


def test_recorded_names_preserve_lord_and_alternate_forms() -> None:
    """
    Keep historical names while avoiding additional peerage and birth-name variants.
    """
    person = Person.model_validate(
        {
            "id": "uk.org.publicwhip/person/10000",
            "other_names": [
                {"family_name": "Example", "given_name": "Jane", "note": "Main"},
                {"name": "J Example", "note": "Alternate"},
                {"family_name": "Example", "given_name": "", "note": "Alternate"},
                {
                    "honorific_prefix": "Baroness",
                    "lordname": "Example",
                    "lordofname": "Somewhere",
                    "surname": "Original",
                    "given_name": "Jane",
                    "note": "Main",
                    "start_date": "2024",
                    "end_date": "2026-11",
                },
                {
                    "honorific_prefix": "Bishop",
                    "lordofname": "Norwich",
                    "note": "Alternate",
                },
            ],
        }
    )

    assert add_person_ids.get_person_names(person) == [
        "Jane Example",
        "J Example",
        "Example",
        "Baroness Example of Somewhere",
        "Bishop of Norwich",
    ]


def test_corrections_load_once_per_run_and_refresh_between_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Reuse one correction snapshot per command while respecting subsequent edits.
    """
    monkeypatch.chdir(tmp_path)
    popolo = Popolo.model_validate(
        {
            "persons": [
                {
                    "id": f"uk.org.publicwhip/person/{10000 + i}",
                    "other_names": [
                        {
                            "given_name": given_name,
                            "family_name": "Example",
                            "note": "Main",
                        }
                    ],
                }
                for i, given_name in enumerate(["Jane", "Alex"])
            ],
            "organizations": [],
            "posts": [],
            "memberships": [],
        }
    )
    monkeypatch.setattr(Popolo, "from_parlparse", lambda: popolo)
    NameCorrectionList(
        root=[NameCorrection(original="alias", canon="Jane Example")]
    ).save()
    APPG(
        slug="example",
        title="Example",
        officers=[Officer(name="Alias", role="Chair", party="")],
        members_list=MemberList(
            members=[
                Member(name="Alias", member_type="mp"),
                Member(name="Unknown", member_type="mp"),
            ]
        ),
    ).save()

    with patch.object(
        NameCorrectionList, "load", wraps=NameCorrectionList.load
    ) as load:
        add_person_ids.add_person_ids()
        assert load.call_count == 1
        saved = APPG.load("example")
        assert saved.officers[0].twfy_id == "uk.org.publicwhip/person/10000"
        assert saved.members_list.members[0].twfy_id == "uk.org.publicwhip/person/10000"

        NameCorrectionList(
            root=[NameCorrection(original="alias", canon="Alex Example")]
        ).save()
        add_person_ids.add_person_ids()
        assert load.call_count == 2

    saved = APPG.load("example")
    assert saved.officers[0].twfy_id == "uk.org.publicwhip/person/10001"
    assert saved.members_list.members[0].twfy_id == "uk.org.publicwhip/person/10001"
    corrections = NameCorrectionList.load()
    assert corrections.as_dict() == {"alias": "alex example"}
    assert {entry.original for entry in corrections} == {"alias", "unknown"}
