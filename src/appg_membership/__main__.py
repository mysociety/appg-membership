import typer
from typer import Typer

app = Typer(pretty_exceptions_enable=False)


def _parse_parliaments(parliament: str):
    from .models import Parliament

    options = {
        "scotland": [Parliament.SCOTLAND],
        "senedd-en": [Parliament.SENEDD_EN],
        "senedd-cy": [Parliament.SENEDD_CY],
        "ni": [Parliament.NI],
        "all": [
            Parliament.SCOTLAND,
            Parliament.SENEDD_EN,
            Parliament.SENEDD_CY,
            Parliament.NI,
        ],
    }
    return options.get(parliament.lower())


@app.command()
def fetch_appg_index(latest_only: bool = False):
    """
    Fetch the APPG index from the UK Parliament website.
    """
    from .fetch_index import fetch_all

    fetch_all(latest_only=latest_only)


@app.command()
def search_for_websites():
    """
    Search for websites of APPGs.
    """
    from .search_agent import update_website

    update_website()


@app.command()
def review_websites():
    """
    Interactive terminal app to review websites found by automatic search.

    Reviews all APPGs with a 'search_precheck' status, allowing you to:
    - Accept the URL (changes status to 'search')
    - Reject the URL (sets URL to None and status to 'bad_search')
    - Provide a manual URL (sets the URL and status to 'manual')
    - Skip for now (keep as 'search_precheck')
    """
    from .website_review import review_website_candidates

    review_website_candidates()


@app.command()
def scrape_memberships(
    refresh_not_found: bool = False,
    refresh_previous_ai: bool = False,
    slug: str = "",
):
    """
    Update the membership of APPGs via scraper.
    """
    from .membership_agent import update_appgs_membership

    update_appgs_membership(
        refresh_not_found=refresh_not_found,
        refresh_previous_ai=refresh_previous_ai,
        slug=slug,
    )


@app.command()
def load_spreadsheets():
    """
    Load all spreadsheets from the APPG website.
    """
    from .load_spreadsheets import load_all_spreadsheets

    load_all_spreadsheets()


@app.command()
def add_person_ids():
    """
    Add person IDs to the data.
    """
    from .add_person_ids import add_person_ids

    add_person_ids()


@app.command()
def build():
    """
    Run the final construction phases.
    """
    from .add_person_ids import add_person_ids
    from .build_data import build

    add_person_ids()
    build()


@app.command()
def correct_unmatched_names(threshold: float = 0.5, max_suggestions: int = 5):
    """
    Interactive terminal app to correct misspelled MP names.
    """
    from .bad_name import correct_names

    correct_names(threshold=threshold, max_suggestions=max_suggestions)


@app.command()
def generate_diffs():
    """
    Generate diffs between the current and previous releases.
    """
    from .diff import generate_diffs

    generate_diffs()


@app.command()
def export_crowdsource(output_path: str | None = None):
    """
    Export an Excel file for external crowdsourcing of APPG information.

    Creates an Excel spreadsheet with information about all APPGs including their current website
    and membership status. The spreadsheet can be used to crowdsource verification of whether
    APPGs have websites or membership lists that weren't found by automatic methods.

    Args:
        output_path: Optional path for the output Excel file. If not provided,
                    a file will be created in data/exports/ with a timestamp.
    """
    from .export_data import export_for_crowdsource

    export_for_crowdsource(output_path)


@app.command()
def find_old_members(format: str = "list"):
    """
    Find APPGs that have members who are no longer MPs.

    Args:
        format: Output format - 'list' for individual messages or 'table' for summary table sorted by percentage

    With 'list' format: Shows individual messages for each person who is listed
    as a member of an APPG but is no longer in Parliament.

    With 'table' format: Shows a summary table with APPG names, total number of
    'old' members (those no longer serving in Parliament), and the proportion
    of old members to total members, sorted by percentage (highest to lowest).
    """
    from .old_members import find_appgs_with_old_members

    if format not in ["list", "table"]:
        print("Error: format must be either 'list' or 'table'")
        return

    find_appgs_with_old_members(format_type=format)


@app.command()
def blank_membership_information(appg_slug: str):
    """
    Blank the membership information for a given APPG slug.

    This command is used to remove outdated or inaccurate membership information
    that was automatically sourced. It will:
    - Set the source method to 'empty'
    - Remove all members from the membership list
    - Clear source URLs and update timestamp
    - Save the changes to the APPG file

    Args:
        appg_slug: The slug of the APPG to blank membership information for
    """
    from .blank_membership import blank_membership_information

    success = blank_membership_information(appg_slug)
    if not success:
        raise typer.Exit(1)


@app.command()
def load_manual_data(skip_download: bool = False, slug: str = ""):
    """
    Load manual APPG membership data from Google Docs.

    Downloads a Google Docs document as markdown and parses it to extract
    APPG membership information. The document structure should be:
    - H1: Ignored
    - H2: APPG title
    - H3: Either "notes" (ignored) or "members" (processed)
    - If no H3s under H2, all content is treated as members
    - Members are parsed as any line with content

    Args:
        skip_download: If True, skip downloading and use existing markdown file
        slug: If provided, only update this specific APPG slug
    """
    from .load_manual_data import load_manual_data

    success = load_manual_data(skip_download=skip_download, target_slug=slug)
    if not success:
        raise typer.Exit(1)


@app.command()
def scotland():
    """
    Download and convert Scotland Cross-Party Group data to APPG format.

    This command fetches official Cross-Party Group data from the Scottish Parliament API
    and converts it to the standard APPG format. It will:
    - Fetch all current Cross-Party Groups (active groups with no end date)
    - Download official member roles and membership data
    - Use the MySoc Popolo library to get person details with TWFY/MNIS IDs
    - Generate public parliament.scot URLs for each group
    - Save one JSON file per group in data/cpg_scotland/
    - Mark membership data as 'official' source method

    The output files follow the same format as UK APPGs for consistency.
    """
    from .scotland import download_and_convert_scotland_data

    try:
        download_and_convert_scotland_data()
    except Exception as e:
        print(f"Error downloading Scotland data: {e}")
        raise typer.Exit(1)


@app.command()
def ni_assembly():
    """
    Download and convert NI Assembly All-Party Group data to APPG format.

    This command fetches official All-Party Group data from the NI Assembly API
    and converts it to the standard APPG format. It will:
    - Fetch all current All-Party Groups from the NI Assembly organisations API
    - Download member roles and filter to APG role assignments
    - Scrape purpose and financial benefits from detail pages
    - Save one JSON file per group in data/apg_ni/
    - Mark membership data as 'official' source method

    The output files follow the same format as UK APPGs for consistency.
    """
    from .ni_assembly import download_and_convert_ni_data

    try:
        download_and_convert_ni_data()
    except Exception as e:
        print(f"Error downloading NI Assembly data: {e}")
        raise typer.Exit(1)


@app.command()
def senedd():
    """
    Download and convert Senedd Cross-Party Group data to APPG format.

    This command scrapes Cross-Party Group data from the Senedd website
    and converts it to the standard APPG format. It will:
    - Fetch the list of Cross-Party Groups from business.senedd.wales
    - For each group, fetch both the English and Welsh language detail pages
    - Extract name, purpose, officers, and members
    - Save one JSON file per group in data/cpg_senedd_en/ (English)
      and data/cpg_senedd_cy/ (Welsh)
    - Mark membership data as 'official' source method

    The English and Welsh versions are treated as separate parliaments
    ('senedd-en' and 'senedd-cy') to mirror how they will be presented
    in TheyWorkForYou.
    """
    from .senedd import download_and_convert_senedd_data

    try:
        download_and_convert_senedd_data()
    except Exception as e:
        print(f"Error downloading Senedd data: {e}")
        raise typer.Exit(1)


@app.command()
def assign_categories(parliament: str = "all", all_groups: bool = False):
    """
    Run LLM category assignment for devolved parliaments.

    By default this only classifies groups that currently have no categories.
    Use --all-groups to reclassify all groups in the selected parliament(s).
    """
    from .category_assignment import assign_categories

    selected_parliaments = _parse_parliaments(parliament)
    if selected_parliaments is None:
        print(
            "Error: parliament must be one of: all, scotland, senedd-en, senedd-cy, ni"
        )
        raise typer.Exit(1)

    updated_count = assign_categories(
        parliaments=selected_parliaments,
        only_missing=not all_groups,
    )
    print(f"Assigned categories for {updated_count} groups")


def main():
    """
    Main function to run the Typer app.
    """
    app()


if __name__ == "__main__":
    main()
