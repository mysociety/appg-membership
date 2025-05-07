from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

import httpx
import rich
from bs4 import BeautifulSoup, Tag
from pydantic.networks import HttpUrl
from tqdm import tqdm

from appg_membership.config import settings
from appg_membership.models import (
    APPG,
    AGMDetails,
    ContactDetails,
    Officer,
    WebsiteSource,
    register_dates,
)


def _get_value_from_row(row: Tag) -> str:
    """
    Helper: return the *second* <td> cell's inner text for a given row.
    """
    cells = row.find_all("td")
    if len(cells) < 2:
        return ""
    return cells[1].get_text(strip=True, separator=" ")


def _parse_table_by_header(tables: List[Tag], header_text: str) -> Optional[Tag]:
    """
    Find the first <table> whose first <strong> text matches *header_text*.
    Returns None if no matching table is found.
    """
    for tbl in tables:
        strong = tbl.find("strong")
        if strong and strong.get_text(strip=True) == header_text:
            return tbl
    return None


def _parse_officers(table: Optional[Tag]) -> List[Officer]:
    """Parse officers from the officers table, or return empty list if table is missing."""
    if not table:
        return []

    officers: list[Officer] = []
    rows = table.find_all("tr")[2:]  # skip header rows
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        role = tds[0].get_text(strip=True, separator=" ")
        name = tds[1].get_text(strip=True, separator=" ")
        party = tds[2].get_text(strip=True, separator=" ")

        officers.append(Officer(role=role, name=name, party=party))
    return officers


def _parse_contact_details(table: Optional[Tag]) -> Optional[ContactDetails]:
    """Parse contact details from the contact details table, or return None if table is missing."""
    if not table:
        return None

    # Use <strong> tags as anchors, then read the next siblings' text
    text = table.get_text("\n", strip=True)

    def _extract_block(label: str) -> list[str]:
        """Return lines following *label:* until the next label or end."""
        lines = text.splitlines()
        try:
            start = next(
                i
                for i, line in enumerate(lines)
                if line.lower().startswith(label.lower())
            )
            block: list[str] = []
            for line in lines[start + 1 :]:
                if line.endswith(":"):
                    break
                block.append(line)
            return block
        except StopIteration:
            return []

    reg_block = _extract_block("Registered Contact:")
    pub_block = _extract_block("Public Enquiry Point:")
    sec_block = _extract_block("Secretariat:")
    web_block = _extract_block("Group's Website:")

    rc_name = ""
    rc_addr = None
    if reg_block:
        rc_parts = reg_block[0].split(",", 1) if reg_block else ["", ""]
        rc_name = rc_parts[0].strip()
        if len(rc_parts) > 1:
            rc_addr = rc_parts[1].strip()

    if web_block:
        web = WebsiteSource(status="register", url=HttpUrl(web_block[0]))
    else:
        web = WebsiteSource()

    return ContactDetails(
        registered_contact_name=rc_name or None,
        registered_contact_address=rc_addr,
        registered_contact_email=next(
            (
                item.split(":", 1)[1].strip()
                for item in reg_block
                if item.lower().startswith("email:")
            ),
            None,
        ),
        public_enquiry_point_name=pub_block[0] if pub_block else None,
        public_enquiry_point_email=next(
            (
                item.split(":", 1)[1].strip()
                for item in pub_block
                if item.lower().startswith("email:")
            ),
            None,
        ),
        secretariat=" ".join(sec_block) if sec_block else None,
        website=web,
    )


def _parse_agm_details(table: Optional[Tag]) -> Optional[AGMDetails]:
    """Parse AGM details from the AGM table, or return None if table is missing."""
    if not table:
        return None

    rows = table.find_all("tr")[1:]  # first row is the table caption
    mapping = {}

    # Build the mapping more defensively
    for r in rows:
        td = r.find("td")
        if not td:
            continue
        key = td.get_text(strip=True)
        mapping[key] = _get_value_from_row(r)

    def _parse_date(s: Optional[str]) -> Optional[date]:
        """Parse a date string or return None if invalid."""
        if not s:
            return None
        try:
            return datetime.strptime(s.strip(), "%d/%m/%Y").date()
        except (ValueError, AttributeError):
            return None

    # Get values with fallbacks for missing keys
    agm_date_str = mapping.get("Date of most recent AGM in this Parliament")
    statement_str = mapping.get(
        "Did the group publish an income and expenditure statement relating to the AGM above?"
    )
    reporting_year = mapping.get("Reporting year")
    deadline_str = mapping.get("Next reporting deadline")

    return AGMDetails(
        date_of_most_recent_agm=_parse_date(agm_date_str),
        published_income_expenditure_statement=statement_str or False,
        reporting_year=reporting_year,
        next_reporting_deadline=_parse_date(deadline_str),
    )


def parse_appg_html(html: str, *, slug: str, source_url: str, index_date: str) -> APPG:
    """
    Parse one APPG register page's HTML and return an APPG instance.
    The function is tolerant of missing tables and content.
    """
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table", class_="basicTable")

    # Default values in case tables are missing
    title = ""
    purpose = None
    category = None
    officers = []
    contact_details = ContactDetails(website=WebsiteSource())
    agm = None
    registrable_benefits = None

    # --- 1. Overview table (should always exist) ---------------------------- #
    if tables:
        overview = tables[0]
        overview_rows = overview.find_all("tr")
        if len(overview_rows) > 0:
            title = _get_value_from_row(overview_rows[0])
        if len(overview_rows) > 1:
            purpose = _get_value_from_row(overview_rows[1])
        if len(overview_rows) > 2:
            category = _get_value_from_row(overview_rows[2])

    # --- 2. Officers -------------------------------------------------------- #
    officers_table = _parse_table_by_header(tables, "Officers")
    officers = _parse_officers(officers_table)

    # --- 3. Contact details ------------------------------------------------- #
    contact_table = _parse_table_by_header(tables, "Contact Details")
    contact_details = _parse_contact_details(contact_table) or contact_details

    # --- 4. AGM details ----------------------------------------------------- #
    agm_table = _parse_table_by_header(tables, "Annual General Meeting")
    agm = _parse_agm_details(agm_table)

    # --- 5. Registrable benefits ------------------------------------------- #
    benefits_table = _parse_table_by_header(
        tables, "Registrable benefits received by the group"
    )
    if benefits_table:
        rows = benefits_table.find_all("tr")
        if len(rows) > 1:
            benefits_text = rows[1].get_text(strip=True)
            registrable_benefits = (
                None if benefits_text.lower() == "none" else benefits_text
            )

    return APPG(
        title=title,
        slug=slug,
        purpose=purpose,
        category=category,
        officers=officers,
        contact_details=contact_details,
        agm=agm,
        registrable_benefits=registrable_benefits,
        source_url=HttpUrl(source_url),
        index_date=index_date,
    )


def get_appg_data(url: str, index_date: str) -> APPG:
    """
    Fetch the HTML for a given APPG register page and return an APPG instance.
    """
    slug = url.split("/")[-1].split(".")[0]

    headers = {"User-Agent": settings.PARL_USERAGENT}
    response = httpx.get(url, headers=headers)
    response.raise_for_status()
    return parse_appg_html(
        response.text, slug=slug, source_url=url, index_date=index_date
    )


def fetch_from_index(index_date: str, is_latest: bool = False):
    url_folder = f"https://publications.parliament.uk/pa/cm/cmallparty/{ index_date }/"
    index_url = url_folder + "contents.htm"

    headers = {"User-Agent": settings.PARL_USERAGENT}
    contents = httpx.get(index_url, headers=headers).text

    soup = BeautifulSoup(contents, "lxml")
    links = soup.find_all("a")
    urls = []

    # capture relative links to the same folder (e.g. no slashes) e.g. 'canada.htm' - and prepend the folder
    # url to them
    for link in links:
        href = link.get("href")
        if href and href.endswith(".htm"):
            # prepend the folder URL
            urls.append(url_folder + href)

    # remove duplicates
    urls = list(set(urls))
    urls.sort()

    rich.print(f"Found {len(urls)} APPG URLs in the index.")

    for u in tqdm(urls):
        slug = u.split("/")[-1].split(".")[0]
        tqdm.write(f"Fetching APPG: {slug}")
        appg = get_appg_data(u, index_date=index_date)
        appg.save(release=index_date)
        if is_latest:
            try:
                current = APPG.load(slug)
                appg.update_from(current)
            except FileNotFoundError:
                rich.print(f"APPG {slug} not found in the current index.")
            appg.save()


def fetch_all():
    for register_date in register_dates:
        rich.print(f"Fetching APPGs from register date: {register_date}")
        fetch_from_index(register_date, is_latest=register_date == register_dates[-1])


if __name__ == "__main__":
    fetch_all()
