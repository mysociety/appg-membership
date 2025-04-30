from datetime import date
from pathlib import Path

import pandas as pd

from appg_membership.models import APPG, Member

spreadsheet_path = Path("data", "raw", "september")

spreadsheet_date = date.fromisoformat("2024-12-01")


def load_all_spreadsheets():
    # for each of the xlsx files in spreadsheet_path
    # read the file, get the D and E tabs - table structure starts at row 7

    all_d = []
    all_e = []

    for file in spreadsheet_path.glob("*.xlsx"):
        # read the file
        slug = file.stem
        xls = pd.ExcelFile(file)
        # print the sheet names
        # get the D and E tabs
        d_tab = pd.read_excel(xls, sheet_name="D. Parliamentary Membership ", header=6)
        e_tab = pd.read_excel(
            xls, sheet_name="E. Non-Parliamentary Membership", header=6
        )

        # drop all na rows
        d_tab = d_tab.dropna(how="all")
        e_tab = e_tab.dropna(how="all")
        d_tab = d_tab[d_tab["Name"] != "Add more rows as needed"]
        e_tab = e_tab[e_tab["Name"] != "Add more rows as needed"]
        d_tab["slug"] = slug
        e_tab["slug"] = slug

        all_d.append(d_tab)
        all_e.append(e_tab)

    e_tab = pd.concat(all_e)
    d_tab = pd.concat(all_d)

    e_tab = e_tab.rename(columns=lambda x: x.strip())
    d_tab = d_tab.rename(columns=lambda x: x.strip())

    options = {
        "HoC": "mp",
        "HoL": "lord",
        "House of Commons": "mp",
        "Commons": "mp",
        "House of Lords": "lord",
        "Lords": "lord",
    }
    d_tab["House"] = d_tab["House"].replace(options)

    def get_house(row: pd.Series) -> str:
        if not pd.isna(row["House"]):
            return row["House"]

        name = row["Name"]
        lord_options = ["Lord", "Baroness", "Baron", "Lady", "Viscount", "Dame"]

        if " MP" in name:
            return "mp"
        if any([x in name for x in lord_options]):
            return "lord"

        return "mp"

    d_tab["House"] = d_tab.apply(get_house, axis=1)
    d_tab["Role (e.g. Chair, Officer, Treasurer)"] = d_tab[
        "Role (e.g. Chair, Officer, Treasurer)"
    ].fillna("Member")

    for slug, gdf in d_tab.groupby("slug"):
        appg = APPG.load(str(slug))
        if appg.members_list.source_method in ["empty", "manual"]:
            appg.members_list.source_method = "manual"
            appg.members_list.last_updated = spreadsheet_date
            appg.members_list.members = [
                Member(
                    name=row["Name"],
                    is_officer=row["Role (e.g. Chair, Officer, Treasurer)"] != "Member",
                    member_type=row["House"],
                )
                for _, row in gdf.iterrows()
            ]
        appg.save()


if __name__ == "__main__":
    load_all_spreadsheets()
