from datetime import date
from pathlib import Path

import pandas as pd
from mysoc_validator import Popolo

from appg_membership.models import APPGList, register_dates

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


def build_register():
    items = APPGList.load()

    data = [x.flattened_dict() for x in items]

    df = pd.DataFrame(data)
    df.to_parquet(package_path / "register.parquet", index=False)


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


def build_members():
    """
    Missing step here is to bring in the officers.
    """
    items = APPGList.load()
    pop = Popolo.from_parlparse()

    data = []
    for x in items:
        for officer in x.officers:
            canon_name = None
            if officer.twfy_id:
                person = pop.persons[officer.twfy_id]
                canon_name = person.get_main_name()
                if canon_name:
                    canon_name = canon_name.nice_name()
            item = {}
            item["name"] = officer.name
            item["officer_role"] = officer.role
            item["twfy_id"] = officer.twfy_id
            item["mnis_id"] = officer.mnis_id
            item["canon_name"] = canon_name
            item["appg"] = x.slug
            item["is_officer"] = True
            item["member_type"] = officer_type(officer.name)
            item["source"] = "parliament"
            item["last_updated"] = last_register
            item["url_source"] = str(x.source_url)
            data.append(item)
        for member in x.members_list.members:
            canon_name = None
            if member.twfy_id:
                person = pop.persons[member.twfy_id]
                canon_name = person.get_main_name()
                if canon_name:
                    canon_name = canon_name.nice_name()
            item = member.model_dump()
            item["canon_name"] = canon_name
            item["appg"] = x.slug
            item["source"] = x.members_list.source_method
            item["last_updated"] = x.members_list.last_updated
            item["url_source"] = str(x.members_list.source_url)
            data.append(item)

    df = pd.DataFrame(data)

    # default is the twfy_id column, but where this is blank use name column

    df["combo_col"] = df.apply(
        lambda x: x["twfy_id"] if not pd.isna(x["twfy_id"]) else x["name"], axis=1
    )
    # dedupe by this column + slug - prefering items with a source of parliament - so
    # sort those to the top first
    df["is_not_parliament_source"] = df["source"].apply(
        lambda x: 0 if x == "parliament" else 1
    )
    df = df.sort_values(by=["is_not_parliament_source"])

    df = df.drop_duplicates(subset=["combo_col", "appg"], keep="first")

    df = df.sort_values(["appg", "is_not_parliament_source", "twfy_id"])

    # remove the combo_col
    df = df.drop(columns=["combo_col", "is_not_parliament_source"])

    df.to_parquet(package_path / "members.parquet", index=False)


def build_categories():
    """
    Build the categories for the APPG membership package.
    """
    items = APPGList.load()

    data = []

    for item in items:
        for category in item.categories:
            data.append(
                {
                    "appg_slug": item.slug,
                    "category_slug": category.name,
                    "category_name": category.value,
                }
            )
    df = pd.DataFrame(data)
    df.to_parquet(package_path / "categories.parquet", index=False)


def build():
    """
    Build the data files for the APPG membership package.
    """
    build_register()
    build_members()
    build_categories()


if __name__ == "__main__":
    build()
