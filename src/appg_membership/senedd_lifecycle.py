from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from mysoc_validator import Popolo
from mysoc_validator.models.popolo import Chamber, IdentifierScheme
from pydantic import HttpUrl

from .models import APPG, Member, Officer, Parliament
from .senedd_models import MembershipValidity, SeneddTerm

SENEDD_PARLIAMENTS = {Parliament.SENEDD_EN, Parliament.SENEDD_CY}
MONITORING_REPORT = (
    "https://senedd.wales/media/uxuhemdd/cpg-monitoring-report-2024-25.pdf"
)
SIXTH_ARCHIVE = (
    "https://senedd.wales/archive/sixth-senedd-2021-2026/"
    "cross-party-groups-sixth-senedd-2021-2026/"
)
SENEDD_TERMS = {
    6: SeneddTerm(
        number=6,
        starts_on=date(2021, 5, 6),
        registration_opens_on=date(2021, 5, 6),
        ends_on=date(2026, 4, 8),
        evidence_url=HttpUrl(MONITORING_REPORT),
    ),
    7: SeneddTerm(
        number=7,
        starts_on=date(2026, 5, 8),
        registration_opens_on=date(2026, 7, 1),
        evidence_url=HttpUrl(MONITORING_REPORT),
    ),
}


class ServiceSpell(NamedTuple):
    """
    A continuous period in the Senedd, merging party changes within that period.
    """

    starts_on: date
    ends_on: date
    end_reason: str | None = None


class SeneddMembershipChecker:
    """
    Resolve service in the Senedd without treating another chamber as eligibility.
    """

    def __init__(self, popolo: Popolo) -> None:
        self.popolo = popolo
        self.spells: dict[str, list[ServiceSpell]] = {}

    def service_spells(self, member: Member | Officer) -> list[ServiceSpell]:
        """
        Return exact, continuous service spells; uncertain dates cannot verify service.
        """
        try:
            if member.twfy_id:
                person = self.popolo.persons[member.twfy_id]
            elif member.mnis_id:
                person = self.popolo.persons.from_identifier(
                    member.mnis_id, scheme=IdentifierScheme.SENEDD
                )
            else:
                return []
        except (KeyError, ValueError):
            return []
        if person.id in self.spells:
            return self.spells[person.id]

        spells: list[ServiceSpell] = []
        for membership in person.memberships():
            post = membership.post()
            chamber = post.organization_id if post else membership.organization_id
            if chamber != Chamber.SENEDD:
                continue
            if not isinstance(membership.start_date, date) or not isinstance(
                membership.end_date, date
            ):
                continue
            spells.append(
                ServiceSpell(
                    membership.start_date, membership.end_date, membership.end_reason
                )
            )
        merged: list[ServiceSpell] = []
        for spell in sorted(spells):
            adjacent_party_change = bool(
                merged
                and merged[-1].end_reason
                in {"changed_party", "whip_removed", "whip_restored"}
                and merged[-1].ends_on < date.max
                and spell.starts_on == merged[-1].ends_on + timedelta(days=1)
            )
            if merged and (
                spell.starts_on <= merged[-1].ends_on or adjacent_party_change
            ):
                previous = merged.pop()
                merged.append(
                    ServiceSpell(
                        previous.starts_on,
                        max(previous.ends_on, spell.ends_on),
                        spell.end_reason,
                    )
                )
            else:
                merged.append(spell)
        self.spells[person.id] = merged
        return merged

    def relevant_spell(
        self, member: Member | Officer, appg: APPG
    ) -> ServiceSpell | None:
        """
        Anchor service to the membership evidence, so a later return cannot revive it.
        """
        registration = appg.senedd_registration
        if not registration or registration.term not in SENEDD_TERMS:
            return None
        term = SENEDD_TERMS[registration.term]
        validity = member.validity or MembershipValidity()
        observed_on = (
            validity.observed_on
            or appg.members_list.last_updated
            or registration.observed_on
        )
        spells = [
            spell
            for spell in self.service_spells(member)
            if spell.ends_on > term.starts_on
            and (term.ends_on is None or spell.starts_on < term.ends_on)
        ]
        if observed_on:
            matching = [
                spell
                for spell in spells
                if spell.starts_on <= observed_on < spell.ends_on
            ]
            if matching:
                return matching[0]
            # A stale source can still list an MS after they have left.
            spells = [spell for spell in spells if spell.starts_on <= observed_on]
            return spells[-1] if spells else None
        # Legacy evidence with no observation date cannot establish a later return.
        return spells[0] if spells else None


def bound_senedd_group(appg: APPG, checker: SeneddMembershipChecker) -> APPG:
    """
    Derive the latest possible ends without changing the source record or its dates.
    """
    bounded = appg.model_copy(deep=True)
    registration = bounded.senedd_registration
    if not registration or registration.term not in SENEDD_TERMS:
        return bounded
    term = SENEDD_TERMS[registration.term]
    if term.ends_on and (
        registration.valid_until is None or term.ends_on < registration.valid_until
    ):
        registration.valid_until = term.ends_on
        registration.end_reason = "term_ended"
    for member in [*bounded.officers, *bounded.members_list.members]:
        validity = member.validity or MembershipValidity()
        validity.observed_on = validity.observed_on or bounded.members_list.last_updated
        if validity.end_reason in {"term_ended", "left_senedd"}:
            validity.valid_until = None
            validity.end_reason = None
        if registration.valid_until and (
            validity.valid_until is None
            or registration.valid_until < validity.valid_until
        ):
            validity.valid_until = registration.valid_until
            validity.end_reason = registration.end_reason
        if is_senedd_member(member):
            spell = checker.relevant_spell(member, bounded)
            if (
                spell
                and spell.ends_on != date.max
                and (
                    validity.valid_until is None or spell.ends_on < validity.valid_until
                )
            ):
                validity.valid_until = spell.ends_on
                validity.end_reason = "left_senedd"
        member.validity = validity
    return bounded


def is_senedd_member(member: Member | Officer) -> bool:
    """
    Identify parliamentary officers as well as ordinary MS members.
    """
    return (
        member.member_type == "ms"
        if isinstance(member, Member)
        else bool(
            member.twfy_id
            or member.mnis_id
            or re.search(r"\b(?:MS|AS)(?:\s*\([^)]*\))?$", member.name)
        )
    )


def registration_is_current(appg: APPG, as_of: date) -> bool:
    """
    Require verified evidence in a configured term and honour all closure bounds.
    """
    registration = appg.senedd_registration
    if not registration or not registration.verified:
        return False
    term = SENEDD_TERMS.get(registration.term)
    if not term or as_of < term.registration_opens_on:
        return False
    starts = registration.valid_from or registration.observed_on
    ends = [end for end in (term.ends_on, registration.valid_until) if end]
    return (starts is None or starts <= as_of) and all(as_of < end for end in ends)


def membership_is_current(
    member: Member | Officer,
    appg: APPG,
    checker: SeneddMembershipChecker,
    as_of: date,
) -> bool:
    """
    Check both registration and uninterrupted service since the membership evidence.
    """
    if member.removed or not registration_is_current(appg, as_of):
        return False
    validity = member.validity or MembershipValidity()
    if validity.valid_from and as_of < validity.valid_from:
        return False
    if validity.observed_on and as_of < validity.observed_on:
        return False
    if validity.valid_until and as_of >= validity.valid_until:
        return False
    if is_senedd_member(member):
        spell = checker.relevant_spell(member, appg)
        return spell is not None and spell.starts_on <= as_of < spell.ends_on
    return True


def archive_group(
    appg: APPG, data_dir: Path, *, captured_on: date | None = None
) -> Path:
    """
    Preserve snapshots named by capture date, with a hash to distinguish versions.

    Repeated content retains its first filename, even when archived on a later day.
    The capture date is independent of source observation and membership dates.
    """
    registration = appg.senedd_registration
    identity = registration.id if registration else f"unverified-{appg.slug}"
    content = appg.model_dump_json(indent=2)
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    folder = data_dir / "history" / str(appg.parliament) / identity
    folder.mkdir(parents=True, exist_ok=True)
    candidates = [
        folder / f"{digest}.json",
        *sorted(folder.glob(f"????-??-??-{digest}.json")),
    ]
    for existing in candidates:
        if existing.exists():
            if existing.read_text(encoding="utf-8").rstrip("\n") != content:
                raise ValueError(
                    f"Snapshot content does not match its hash: {existing}"
                )
            return existing
    captured_on = captured_on or datetime.now(timezone.utc).date()
    path = folder / f"{captured_on.isoformat()}-{digest}.json"
    path.write_text(content + "\n", encoding="utf-8")
    return path


def load_senedd_history(data_dir: Path) -> list[APPG]:
    """
    Load preserved snapshots without mixing them into the default current folders.
    """
    return [
        APPG.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((data_dir / "history").glob("senedd-*/*/*.json"))
    ]
