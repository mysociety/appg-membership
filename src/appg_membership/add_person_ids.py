from mysoc_validator import Popolo
from mysoc_validator.models.popolo import Person

from .models import APPGList, NameCorrectionList, ineligible_person_ids


def get_name_corrections() -> dict[str, str]:
    return NameCorrectionList.load().as_dict()


def name_adaptor(s: str) -> str:
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

    name_fixes = get_name_corrections()

    s = name_fixes.get(s, s)

    return s


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


def add_person_ids():
    items = APPGList.load()
    pop = Popolo.from_parlparse()

    name_lookup: dict[str, Person] = {}

    for person in pop.persons:
        for name in person.names:
            tidied_name = name_adaptor(name.nice_name())
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
                    previous_memberships = previous_person.memberships()
                    current_memberships = person.memberships()
                    # get highest end_date for both
                    previous_highest_end_date = max(
                        (m.end_date for m in previous_memberships if m.end_date),
                        default=None,
                    )
                    current_highest_end_date = max(
                        (m.end_date for m in current_memberships if m.end_date),
                        default=None,
                    )
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
            reduced_name = name_adaptor(officer.name)
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
            reduced_name = name_adaptor(member.name)
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

    NameCorrectionList.load().add_bad_names(bad_names)

    print(f"Added {len(bad_names)} bad names to the list.")


if __name__ == "__main__":
    add_person_ids()
