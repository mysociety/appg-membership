from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Optional

import httpx
import rich
from bs4 import BeautifulSoup, Tag
from pydantic.networks import HttpUrl
from tqdm import tqdm

from appg_membership.classify_appg_agent import classify_appg
from appg_membership.config import settings
from appg_membership.models import (
    APPG,
    AGMDetails,
    AppgCategory,
    ContactDetails,
    Officer,
    WebsiteSource,
    register_dates,
)


def _is_valid_email(email: str) -> bool:
    """
    Validate if an email address is properly formatted.
    Returns True if valid, False otherwise.
    """
    if not email or "@" not in email:
        return False

    # Basic email validation pattern
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


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

    def _extract_section_content(label: str) -> tuple[list[str], Optional[str]]:
        """
        Extract the content after a label (like 'Registered Contact:') and find any email in that section.
        Returns (text_lines, email_address).
        """
        # Find all <strong> tags in the table
        strong_tags = table.find_all("strong")
        target_strong = None

        for strong in strong_tags:
            if strong.get_text(strip=True).lower() == label.lower():
                target_strong = strong
                break

        if not target_strong:
            return [], None

        # Get the parent paragraph and all following paragraphs until we hit another <strong>
        current = target_strong.parent
        content_paragraphs = []
        email = None

        # Process the current paragraph and following siblings
        while current:
            current = current.next_sibling
            if not current:
                break

            # Skip non-tag elements (like text nodes)
            if not hasattr(current, "name"):
                continue

            # If we hit another paragraph with a <strong> tag, we're done with this section
            if current.name == "p" and current.find("strong"):
                break

            # If this is a paragraph, extract its content
            if current.name == "p":
                # Look for email links in this paragraph
                email_links = current.find_all(
                    "a", href=lambda x: x and x.startswith("mailto:")
                )
                if (
                    email_links and not email
                ):  # Take the first email found in this section
                    extracted_email = email_links[0]["href"].replace("mailto:", "")
                    # Validate the email before storing it
                    if _is_valid_email(extracted_email):
                        email = extracted_email

                # Get the text content (excluding the email link text if present)
                text_content = current.get_text(strip=True)
                if text_content and not text_content.startswith("Email:"):
                    content_paragraphs.append(text_content)

        return content_paragraphs, email

    # Extract sections
    reg_content, reg_email = _extract_section_content("Registered Contact:")
    pub_content, pub_email = _extract_section_content("Public Enquiry Point:")
    sec_content, _ = _extract_section_content("Secretariat:")
    web_content, _ = _extract_section_content("Group's Website:")

    # Parse registered contact details
    rc_name = ""
    rc_addr = None
    if reg_content:
        # The first line usually contains name and address
        first_line = reg_content[0]
        if "," in first_line:
            rc_parts = first_line.split(",", 1)
            rc_name = rc_parts[0].strip()
            rc_addr = rc_parts[1].strip()
        else:
            rc_name = first_line.strip()

    # Parse public enquiry point name
    pub_name = pub_content[0] if pub_content else None

    # Parse website
    if web_content:
        web = WebsiteSource(status="register", url=HttpUrl(web_content[0]))
    else:
        web = WebsiteSource()

    return ContactDetails(
        registered_contact_name=rc_name or None,
        registered_contact_address=rc_addr,
        registered_contact_email=reg_email,
        public_enquiry_point_name=pub_name,
        public_enquiry_point_email=pub_email,
        secretariat=" ".join(sec_content) if sec_content else None,
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


def _parse_registrable_benefits(
    table: Optional[Tag],
) -> tuple[Optional[str], list[dict[str, str]]]:
    """
    Parse registrable benefits from the benefits table.
    Returns a tuple of:
    - Simple benefit text (for backward compatibility)
    - List of detailed benefit dictionaries with column names as keys
    """
    if not table:
        return None, []

    rows = table.find_all("tr")
    if len(rows) <= 1:  # Only has header row or empty
        return None, []

    # Check if it has "None" as content
    if len(rows) == 2:
        benefits_text = rows[1].get_text(strip=True)
        if benefits_text.lower() == "none":
            return None, []

    # Process detailed benefits table
    detailed_benefits: list[dict[str, str]] = []
    current_benefit_type = ""
    header_cells = []

    # Analyze the table structure
    for row_idx, row in enumerate(rows):
        cells = row.find_all("td")
        if not cells:
            continue

        # Check if this is a category header row (spans multiple columns)
        colspan = cells[0].get("colspan")
        if colspan and int(colspan) > 1:
            # This is a category header row
            current_benefit_type = cells[0].get_text(strip=True)
            continue

        # If this has 4 columns and looks like a header row
        if len(cells) == 4 and any("Source" in cell.get_text() for cell in cells):
            # This is the header row - grab the column names
            header_cells = [cell.get_text(strip=True) for cell in cells]
            continue

        # If this has 4 columns and we have headers, it's a data row
        if len(cells) == 4 and header_cells:
            # Create a dictionary with the original column names as keys
            benefit_data = {
                header_cells[i]: cells[i].get_text(strip=True)
                for i in range(len(cells))
            }

            # Add the benefit type
            benefit_data["benefit_type"] = current_benefit_type

            detailed_benefits.append(benefit_data)

    # For backward compatibility, we also return the simple benefit text
    simple_benefit = current_benefit_type if detailed_benefits else None

    return simple_benefit, detailed_benefits


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
    detailed_benefits = []

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
        registrable_benefits, detailed_benefits = _parse_registrable_benefits(
            benefits_table
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
        detailed_benefits=detailed_benefits,
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

    # Filter out non-APPG URLs (introduction and topical-issues)
    excluded_slugs = ["introduction", "topical-issues"]
    filtered_urls = [
        url for url in urls if url.split("/")[-1].split(".")[0] not in excluded_slugs
    ]

    rich.print(
        f"Found {len(filtered_urls)} APPG URLs in the index (excluded {len(urls) - len(filtered_urls)} non-APPG URLs)."
    )

    for u in tqdm(filtered_urls):
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
            if appg.category != "Subject Group":
                appg.categories = [AppgCategory.COUNTRY_GROUP]
            if len(appg.categories) == 0:
                appg = classify_appg(appg)
            appg.save()


def fetch_all(latest_only: bool = False):
    if latest_only:
        registers = register_dates[-1:]
    else:
        registers = register_dates

    for register_date in registers:
        rich.print(f"Fetching APPGs from register date: {register_date}")
        fetch_from_index(register_date, is_latest=register_date == register_dates[-1])


if __name__ == "__main__":
    fetch_all()
