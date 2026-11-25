from __future__ import annotations

from typing import NamedTuple

from mysoc_validator_fast import (
    AltName,
    ApproxDate,
    BasicPersonName,
    LordName,
    Membership,
    Person,
    Popolo,
)

from .models import APPGList, NameCorrectionList, ineligible_person_ids


class NameCorrections(NamedTuple):
    entries: NameCorrectionList
    lookup: dict[str, str]


def get_name_corrections() -> NameCorrections:
    """
    Load corrections and build their lookup for one matching run.
    """
    entries = NameCorrectionList.load()
    return NameCorrections(entries=entries, lookup=entries.as_dict())


def name_adaptor(s: str, corrections: NameCorrections) -> str:
    """
    Normalise a name using the corrections already loaded for this run.
    """
    s = s.lower().strip()
    # if ends in ' MP' remove it
    if s.endswith(" mp"):
        s = s[:-3]

    s = s.replace("ö", "o")
    s = s.replace("ü", "u")
    s = s.replace("ä", "a")
    s = s.replace("â", "a")
    s = s.replace("ß", "ss")
    s = s.replace("é", "e")
    s = s.replace("ë", "e")
    s = s.replace("è", "e")
    s = s.replace("ê", "e")
    s = s.replace("ç", "c")
    s = s.replace("ñ", "n")

    s = s.replace("the lord ", "lord ")

    # remove prefixes mr ms mrs dr
    prefixes = [
        "dame ",
        "mp ",
        "mr ",
        "ms ",
        "mrs ",
        "dr ",
        "dr. ",
        "rt hon ",
        "sir ",
        "the rt. hon. ",
        "the rt. hon ",
        "the rt hon. ",
        "rt hon. ",
        "baroness",
        "the rt hon ",
        "sir ",
    ]
    for prefix in prefixes:
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()

    postfixes = [" mp", " cbe", " kcb", " obe", "mp / as", " qc"]
    for postfix in postfixes:
        if s.endswith(postfix):
            s = s[: -len(postfix)].strip()

    # if last character is a comma remove
    if s.endswith(","):
        s = s[:-1].strip()

    return corrections.lookup.get(s, s)


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


def get_person_names(person: Person) -> list[str]:
    """
    Format recorded names without adding the fast validator's extra name variants.

    The fast validator exposes recorded names through model_dump rather than names.
    """
    names: list[str] = []
    for name in person.model_dump().get("other_names", []):
        if "family_name" in name:
            names.append(
                BasicPersonName(
                    family_name=name["family_name"],
                    given_name=name.get("given_name") or None,
                ).nice_name()
            )
        elif "name" in name:
            names.append(AltName(name=name["name"]).nice_name())
        else:
            # Name validity dates can be partial and are irrelevant to formatting.
            name.pop("start_date", None)
            name.pop("end_date", None)
            names.append(LordName(**name).nice_name())
    return names


def add_person_ids() -> None:
    items = APPGList.load()
    pop = Popolo.from_parlparse()
    corrections = get_name_corrections()

    name_lookup: dict[str, Person] = {}
    highest_end_dates: dict[str, ApproxDate] = {}

    # The fast validator scans all memberships on each person.memberships() call.
    for membership in pop.memberships.root:
        if not isinstance(membership, Membership):
            continue
        end_date = membership.end_date
        person_id = membership.person_id
        previous_end_date = highest_end_dates.get(person_id)
        if end_date and (not previous_end_date or end_date > previous_end_date):
            highest_end_dates[person_id] = end_date

    for person in pop.persons.root:
        if not isinstance(person, Person):
            continue
        for name in get_person_names(person):
            tidied_name = name_adaptor(name, corrections)
            if tidied_name in name_lookup:
                previous_person = name_lookup[tidied_name]

                # Prefer UK Parliament members (those with datadotparl_id) over devolved parliament members
                # This handles cases like Paul Davies where one is Senedd and one is Commons
                previous_has_datadotparl = (
                    previous_person.get_identifier("datadotparl_id") is not None
                )
                current_has_datadotparl = (
                    person.get_identifier("datadotparl_id") is not None
                )

                # If current has datadotparl_id and previous doesn't, prefer current
                if current_has_datadotparl and not previous_has_datadotparl:
                    name_lookup[tidied_name] = person
                # If previous has datadotparl_id and current doesn't, keep previous
                elif previous_has_datadotparl and not current_has_datadotparl:
                    pass  # Keep previous
                # If both have or both don't have datadotparl_id, use end_date logic
                else:
                    previous_highest_end_date = highest_end_dates.get(
                        previous_person.id
                    )
                    current_highest_end_date = highest_end_dates.get(person.id)
                    # if current is higher than previous, replace
                    if current_highest_end_date and (
                        not previous_highest_end_date
                        or current_highest_end_date > previous_highest_end_date
                    ):
                        name_lookup[tidied_name] = person

            else:
                name_lookup[tidied_name] = person

    bad_names = []

    for item in items:
        for officer in item.officers:
            reduced_name = name_adaptor(officer.name, corrections)
            if reduced_name in name_lookup:
                person = name_lookup[reduced_name]
                officer.twfy_id = person.id
                officer.mnis_id = str(person.get_identifier("datadotparl_id"))
                # Check if this person is ineligible and mark as removed
                if person.id in ineligible_person_ids:
                    officer.removed = True
            else:
                if not is_lord(officer.name):
                    bad_names.append(reduced_name)
        for member in item.members_list.members:
            reduced_name = name_adaptor(member.name, corrections)
            if reduced_name in name_lookup:
                person = name_lookup[reduced_name]
                member.twfy_id = person.id
                member.mnis_id = str(person.get_identifier("datadotparl_id"))
                # Check if this person is ineligible and mark as removed
                if person.id in ineligible_person_ids:
                    member.removed = True
            else:
                if member.member_type == "mp":
                    bad_names.append(reduced_name)
        item.save()

    bad_names = list(set(bad_names))
    bad_names = [x for x in bad_names if x != "ignore"]
    bad_names.sort()

    corrections.entries.add_bad_names(bad_names)

    print(f"Added {len(bad_names)} bad names to the list.")


if __name__ == "__main__":
    add_person_ids()
