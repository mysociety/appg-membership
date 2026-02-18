import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx
from pydantic import HttpUrl

from .models import (
    APPG,
    ContactDetails,
    Member,
    MemberList,
    Officer,
    Parliament,
    WebsiteSource,
)

# Base URLs for the English and Welsh versions of the Senedd website
SENEDD_EN_BASE = "https://business.senedd.wales/"
SENEDD_CY_BASE = "https://busnes.senedd.cymru/"

LIST_PAGE = "mgListOutsideBodiesByCategory.aspx"
DETAIL_PAGE = "mgOutsideBodyDetails.aspx?ID={body_id}"


def clean_html_text(html: str) -> str:
    """
    Remove HTML tags and clean up whitespace from an HTML string.
    """
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n", text)
    return text.strip()


def create_slug_from_name(name: str) -> str:
    """
    Convert a Senedd Cross-Party Group name to a slug.
    E.g. 'Cross-Party Group on Epilepsy' -> 'epilepsy'
    """
    # Remove common prefixes for Senedd CPGs
    clean_name = re.sub(
        r"^Cross-Party Group on\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    clean_name = re.sub(
        r"^Cross-Party Group for\s+",
        "",
        clean_name,
        flags=re.IGNORECASE,
    )
    clean_name = re.sub(
        r"^Grŵp Trawsbleidiol ar\s+",
        "",
        clean_name,
        flags=re.IGNORECASE,
    )
    clean_name = re.sub(
        r"^Grŵp Trawsbleidiol ar gyfer\s+",
        "",
        clean_name,
        flags=re.IGNORECASE,
    )

    # Remove leading "the " from the topic name
    clean_name = re.sub(r"^the\s+", "", clean_name, flags=re.IGNORECASE)

    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^\w\s-]", "", clean_name.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    slug = slug.strip("-")

    return slug


def fetch_page(url: str) -> str:
    """
    Fetch a web page and return its HTML content.
    """
    response = httpx.get(url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return response.text


def parse_cpg_list(html: str) -> list[dict[str, str]]:
    """
    Parse the Senedd CPG listing page to extract body IDs and names.

    Returns a list of dicts with 'id' and 'name' keys.
    """
    results = []
    # Find all links to mgOutsideBodyDetails.aspx
    pattern = r'<a\s+href="mgOutsideBodyDetails\.aspx\?ID=(\d+)"[^>]*>(.*?)</a>'
    matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)

    for body_id, name_html in matches:
        name = clean_html_text(name_html)
        if name:
            results.append({"id": body_id, "name": name})

    return results


def parse_detail_page_title(html: str) -> str | None:
    """
    Extract the title/name of the CPG from a detail page.
    """
    # Try common ModernGov title patterns
    patterns = [
        r'<h1[^>]*class="[^"]*mgMainTitleSpacer[^"]*"[^>]*>(.*?)</h1>',
        r'<span[^>]*id="[^"]*lblTitle[^"]*"[^>]*>(.*?)</span>',
        r"<h1[^>]*>(.*?)</h1>",
        r"<title>(.*?)(?:\s*-\s*.*?)?</title>",
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if match:
            title = clean_html_text(match.group(1))
            if title:
                return title

    return None


def parse_detail_page_purpose(html: str) -> str | None:
    """
    Extract the purpose/description from a CPG detail page.

    ModernGov outside body detail pages typically have a description
    section that may be in various HTML structures.
    """
    # Try to find a notes/description section
    patterns = [
        # Common pattern: "Notes" section with content
        r'<span[^>]*id="[^"]*lblNotes[^"]*"[^>]*>(.*?)</span>',
        # Content in a section body div after Description/Notes heading
        r'(?:Description|Notes|Purpose)\s*:?\s*</(?:h[23456]|th|strong|b)>\s*</?\w[^>]*>\s*(.*?)(?=<(?:h[23456]|table|div\s+class))',
        # Description in a dedicated div
        r'<div[^>]*id="[^"]*divNotes[^"]*"[^>]*>(.*?)</div>',
        # Try to find content between description heading and next section
        r'<div[^>]*class="[^"]*mgSectionBody[^"]*"[^>]*>(.*?)</div>',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if match:
            purpose = clean_html_text(match.group(1))
            if purpose and len(purpose) > 5:
                return purpose

    return None


def parse_members_table(html: str) -> list[dict[str, str]]:
    """
    Parse the members/representatives table from a detail page.

    Returns a list of dicts with 'name' and 'role' keys.
    """
    members = []

    # Find all table rows that contain member links
    # ModernGov member tables typically have links to mgUserInfo.aspx
    row_pattern = r"<tr[^>]*>(.*?)</tr>"
    rows = re.findall(row_pattern, html, re.DOTALL | re.IGNORECASE)

    for row in rows:
        # Skip header rows
        if "<th" in row.lower():
            continue

        # Extract cells
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)

        if not cells:
            continue

        # First cell usually has the member name (possibly as a link)
        name_html = cells[0]
        # Try to get name from a link first
        link_match = re.search(r"<a[^>]*>(.*?)</a>", name_html, re.DOTALL)
        if link_match:
            name = clean_html_text(link_match.group(1))
        else:
            name = clean_html_text(name_html)

        if not name:
            continue

        # Role is typically in a later cell (often the last one)
        role = ""
        if len(cells) >= 2:
            # Check each cell after name for role content
            for cell in cells[1:]:
                cell_text = clean_html_text(cell)
                if cell_text:
                    role = cell_text

        members.append({"name": name, "role": role})

    return members


def determine_officer_role(role: str) -> bool:
    """
    Determine if a role is an officer role.
    """
    officer_roles = [
        "chair",
        "co-chair",
        "vice chair",
        "vice-chair",
        "deputy chair",
        "secretary",
        "treasurer",
        "cadeirydd",
        "cyd-gadeirydd",
        "is-gadeirydd",
        "ysgrifennydd",
        "trysorydd",
    ]
    return role.lower().strip() in officer_roles


def process_cpg(
    body_id: str,
    en_name: str,
) -> tuple[APPG | None, APPG | None]:
    """
    Process a single Senedd CPG, fetching both English and Welsh versions.

    Returns a tuple of (english_appg, welsh_appg), either of which may be None
    if the page could not be fetched or parsed.
    """
    en_url = urljoin(SENEDD_EN_BASE, DETAIL_PAGE.format(body_id=body_id))
    cy_url = urljoin(SENEDD_CY_BASE, DETAIL_PAGE.format(body_id=body_id))

    slug = create_slug_from_name(en_name)

    # Fetch English page
    en_appg = None
    try:
        en_html = fetch_page(en_url)
        en_title = parse_detail_page_title(en_html) or en_name
        en_purpose = parse_detail_page_purpose(en_html)
        en_members_raw = parse_members_table(en_html)

        officers = []
        member_list = []

        for member_data in en_members_raw:
            name = member_data["name"]
            role = member_data["role"]

            if determine_officer_role(role):
                officers.append(
                    Officer(
                        role=role,
                        name=name,
                        party="",
                    )
                )
            else:
                member_list.append(
                    Member(
                        name=name,
                        is_officer=False,
                        member_type="ms",
                    )
                )

        en_appg = APPG(
            slug=slug,
            title=en_title,
            purpose=en_purpose,
            category=None,
            parliament=Parliament.SENEDD_EN,
            officers=officers,
            members_list=MemberList(
                source_method="official",
                source_url=[HttpUrl(en_url)],
                last_updated=None,
                members=member_list,
            ),
            contact_details=ContactDetails(
                website=WebsiteSource(status="register", url=HttpUrl(en_url))
            ),
            agm=None,
            registrable_benefits=None,
            detailed_benefits=[],
            index_date="",
            source_url=HttpUrl(en_url),
            categories=[],
        )
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"  Warning: Could not fetch English page for {en_name}: {e}")

    # Fetch Welsh page
    cy_appg = None
    try:
        cy_html = fetch_page(cy_url)
        cy_title = parse_detail_page_title(cy_html) or en_name
        cy_purpose = parse_detail_page_purpose(cy_html)

        # Members are the same for both languages, reuse from English version
        cy_officers = []
        cy_member_list = []

        if en_appg:
            # Reuse parsed member data from the English version
            cy_officers = en_appg.officers.copy()
            cy_member_list = en_appg.members_list.members.copy()
        else:
            # Parse members from Welsh page as fallback
            cy_members_raw = parse_members_table(cy_html)
            for member_data in cy_members_raw:
                name = member_data["name"]
                role = member_data["role"]

                if determine_officer_role(role):
                    cy_officers.append(
                        Officer(
                            role=role,
                            name=name,
                            party="",
                        )
                    )
                else:
                    cy_member_list.append(
                        Member(
                            name=name,
                            is_officer=False,
                            member_type="ms",
                        )
                    )

        cy_appg = APPG(
            slug=slug,
            title=cy_title,
            purpose=cy_purpose,
            category=None,
            parliament=Parliament.SENEDD_CY,
            officers=cy_officers,
            members_list=MemberList(
                source_method="official",
                source_url=[HttpUrl(cy_url)],
                last_updated=None,
                members=cy_member_list,
            ),
            contact_details=ContactDetails(
                website=WebsiteSource(status="register", url=HttpUrl(cy_url))
            ),
            agm=None,
            registrable_benefits=None,
            detailed_benefits=[],
            index_date="",
            source_url=HttpUrl(cy_url),
            categories=[],
        )
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"  Warning: Could not fetch Welsh page for {en_name}: {e}")

    return en_appg, cy_appg


def save_appg(appg: APPG, data_dir: Path) -> None:
    """
    Save an APPG to a JSON file.
    """
    file_path = data_dir / f"{appg.slug}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(
            appg.model_dump(mode="json", exclude_none=False),
            f,
            indent=2,
            ensure_ascii=False,
        )


def download_and_convert_senedd_data():
    """
    Download Senedd Cross-Party Group data and convert to APPG format.

    This function:
    1. Fetches the list of Cross-Party Groups from the Senedd website
    2. For each group, fetches both the English and Welsh detail pages
    3. Extracts name, purpose, officers, and members
    4. Saves one JSON file per group in data/cpg_senedd_en/ and data/cpg_senedd_cy/

    The generated files follow the same format as UK APPGs for consistency.
    """
    base_dir = Path(__file__).parent.parent.parent / "data"
    en_dir = base_dir / "cpg_senedd_en"
    cy_dir = base_dir / "cpg_senedd_cy"
    en_dir.mkdir(parents=True, exist_ok=True)
    cy_dir.mkdir(parents=True, exist_ok=True)

    print(f"English output directory: {en_dir}")
    print(f"Welsh output directory: {cy_dir}")

    # Fetch the listing page
    print("Fetching Senedd Cross-Party Group listing...")
    list_url = urljoin(SENEDD_EN_BASE, LIST_PAGE)
    list_html = fetch_page(list_url)

    # Parse the listing to get all CPG IDs
    cpg_entries = parse_cpg_list(list_html)
    print(f"Found {len(cpg_entries)} Cross-Party Group entries")

    if not cpg_entries:
        print("Warning: No Cross-Party Groups found on the listing page.")
        return

    en_count = 0
    cy_count = 0

    for entry in cpg_entries:
        body_id = entry["id"]
        name = entry["name"]
        print(f"Processing: {name} (ID: {body_id})")

        en_appg, cy_appg = process_cpg(body_id, name)

        if en_appg:
            save_appg(en_appg, en_dir)
            en_count += 1
            print(
                f"  Saved English: {en_appg.slug} "
                f"({len(en_appg.officers)} officers, "
                f"{len(en_appg.members_list.members)} members)"
            )

        if cy_appg:
            save_appg(cy_appg, cy_dir)
            cy_count += 1
            print(f"  Saved Welsh: {cy_appg.slug}")

    print(f"\nCompleted processing {len(cpg_entries)} Cross-Party Groups")
    print(f"English files saved: {en_count} to {en_dir}")
    print(f"Welsh files saved: {cy_count} to {cy_dir}")
