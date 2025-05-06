from typer import Typer

app = Typer(pretty_exceptions_enable=False)


@app.command()
def fetch_appg_index():
    """
    Fetch the APPG index from the UK Parliament website.
    """
    from .fetch_index import fetch_all

    fetch_all()


@app.command()
def search_for_websites():
    """
    Search for websites of APPGs.
    """
    from .search_agent import update_website

    update_website()


@app.command()
def scrape_memberships():
    """
    Update the membership of APPGs via scraper.
    """
    from .membership_agent import update_appgs_membership

    update_appgs_membership()


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
    from .load_spreadsheets import load_all_spreadsheets

    load_all_spreadsheets()
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


def main():
    """
    Main function to run the Typer app.
    """
    app()


if __name__ == "__main__":
    main()
