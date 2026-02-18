import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx
from mysoc_validator import Popolo
from mysoc_validator.models.popolo import IdentifierScheme
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
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def create_slug_from_name(name: str) -> str:
    """
    Convert a Senedd Cross-Party Group name to a slug.

    Handles the actual format used on the Senedd website:
    E.g. 'Academic Staff in Universities - Cross Party Group' -> 'academic-staff-in-universities'
    E.g. 'Staff Academaidd mewn Prifysgolion - Grŵp Trawsbleidiol' -> 'staff-academaidd-mewn-prifysgolion'
    """
    # Remove trailing " - Cross Party Group" or " - Grŵp Trawsbleidiol" suffix
    clean_name = re.sub(
        r"\s*-\s*Cross Party Group\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    clean_name = re.sub(
        r"\s*-\s*Grŵp Trawsbleidiol\s*$",
        "",
        clean_name,
        flags=re.IGNORECASE,
    )

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

    The Senedd ModernGov pages use:
    <h2 class="mgSubTitleTxt">Academic Staff in Universities - Cross Party Group</h2>
    """
    # Try the specific ModernGov subtitle pattern first (most reliable)
    patterns = [
        r'<h2[^>]*class="mgSubTitleTxt"[^>]*>(.*?)</h2>',
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

    The Senedd ModernGov pages have a description in a <div class="mgWordPara">
    section. The purpose text sits between the "Purpose"/"Diben" heading and the
    "Office-holders"/"Deiliaid swyddi" (or "Documentation"/"Dogfennau") heading.
    """
    # Find the mgWordPara section which contains the description
    word_para_match = re.search(
        r'<div class="mgWordPara">(.*?)</div>\s*</div>', html, re.DOTALL
    )
    if not word_para_match:
        return None

    content = word_para_match.group(1)

    # Extract just the purpose text between Purpose/Diben heading and
    # Office-holders/Deiliaid swyddi or Documentation/Dogfennau
    purpose_match = re.search(
        r"(?:Purpose|Diben)(.*?)(?:Office-holders|Deiliaid swyddi|Documentation|Dogfennau)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if purpose_match:
        purpose = re.sub(r"<[^>]+>", "", purpose_match.group(1))
        purpose = unescape(purpose)
        purpose = re.sub(r"\s+", " ", purpose)
        purpose = purpose.strip().strip("\xa0").strip()
        if purpose:
            return purpose

    return None


def parse_members_list(html: str) -> list[dict[str, str]]:
    """
    Parse the members list from a Senedd CPG detail page.

    The Senedd pages use a <ul class="mgBulletList"> with <li> items:
      <li><a href="mgUserInfo.aspx?UID=332">Mike Hedges MS</a> &#40;Chair&#41; </li>
    Roles are in HTML-encoded parentheses: &#40; = ( and &#41; = )

    Returns a list of dicts with 'name', 'role', and 'senedd_id' keys.
    The senedd_id is extracted from the mgUserInfo.aspx?UID=NNN link.
    """
    members = []

    # Find the members bullet list (comes after Members/Aelodau heading)
    list_match = re.search(
        r'<h2[^>]*>(?:Members|Aelodau)</h2>\s*<ul\s+class="mgBulletList"[^>]*>(.*?)</ul>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not list_match:
        # Fallback: try any mgBulletList
        list_match = re.search(
            r'<ul\s+class="mgBulletList"[^>]*>(.*?)</ul>',
            html,
            re.DOTALL | re.IGNORECASE,
        )

    if not list_match:
        return members

    list_html = list_match.group(1)
    items = re.findall(r"<li>(.*?)</li>", list_html, re.DOTALL)

    for item in items:
        # Extract senedd_id from mgUserInfo.aspx?UID=NNN link
        senedd_id = ""
        uid_match = re.search(r"mgUserInfo\.aspx\?UID=(\d+)", item, re.IGNORECASE)
        if uid_match:
            senedd_id = uid_match.group(1)

        # Extract name from link
        link_match = re.search(r"<a[^>]*>(.*?)</a>", item, re.DOTALL)
        if link_match:
            name = re.sub(r"<[^>]+>", "", link_match.group(1)).strip()
        else:
            name = re.sub(r"<[^>]+>", "", item).strip()

        if not name:
            continue

        # Extract role from HTML-encoded parentheses &#40;...&#41;
        role = ""
        role_match = re.search(r"&#40;(.*?)&#41;", item)
        if role_match:
            role = unescape(role_match.group(1)).strip()

        members.append({"name": name, "role": role, "senedd_id": senedd_id})

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


def lookup_twfy_id(senedd_id: str, popolo: Popolo | None) -> str | None:
    """
    Look up a TWFY person ID from a Senedd UID using the Popolo dataset.

    Returns the TWFY person ID string (e.g. 'uk.org.publicwhip/person/26141')
    or None if not found.
    """
    if not popolo or not senedd_id:
        return None

    try:
        person = popolo.persons.from_identifier(
            senedd_id, scheme=IdentifierScheme.SENEDD
        )
        return person.id
    except (KeyError, ValueError):
        return None


def process_cpg(
    body_id: str,
    en_name: str,
    popolo: Popolo | None = None,
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
        en_members_raw = parse_members_list(en_html)

        officers = []
        member_list = []

        for member_data in en_members_raw:
            name = member_data["name"]
            role = member_data["role"]
            senedd_id = member_data["senedd_id"]
            twfy_id = lookup_twfy_id(senedd_id, popolo)

            if determine_officer_role(role):
                officers.append(
                    Officer(
                        role=role,
                        name=name,
                        party="",
                        mnis_id=senedd_id or None,
                        twfy_id=twfy_id,
                    )
                )
            else:
                member_list.append(
                    Member(
                        name=name,
                        is_officer=False,
                        member_type="ms",
                        mnis_id=senedd_id or None,
                        twfy_id=twfy_id,
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
            # Deep copy member data from the English version
            cy_officers = [o.model_copy() for o in en_appg.officers]
            cy_member_list = [m.model_copy() for m in en_appg.members_list.members]
        else:
            # Parse members from Welsh page as fallback
            cy_members_raw = parse_members_list(cy_html)
            for member_data in cy_members_raw:
                name = member_data["name"]
                role = member_data["role"]
                senedd_id = member_data["senedd_id"]
                twfy_id = lookup_twfy_id(senedd_id, popolo)

                if determine_officer_role(role):
                    cy_officers.append(
                        Officer(
                            role=role,
                            name=name,
                            party="",
                            mnis_id=senedd_id or None,
                            twfy_id=twfy_id,
                        )
                    )
                else:
                    cy_member_list.append(
                        Member(
                            name=name,
                            is_officer=False,
                            member_type="ms",
                            mnis_id=senedd_id or None,
                            twfy_id=twfy_id,
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
    4. Stores Senedd UIDs as mnis_id and converts to TWFY IDs using Popolo
    5. Saves one JSON file per group in data/cpg_senedd_en/ and data/cpg_senedd_cy/

    The generated files follow the same format as UK APPGs for consistency.
    """
    base_dir = Path(__file__).parent.parent.parent / "data"
    en_dir = base_dir / "cpg_senedd_en"
    cy_dir = base_dir / "cpg_senedd_cy"
    en_dir.mkdir(parents=True, exist_ok=True)
    cy_dir.mkdir(parents=True, exist_ok=True)

    print(f"English output directory: {en_dir}")
    print(f"Welsh output directory: {cy_dir}")

    # Initialize Popolo for person lookup (Senedd ID -> TWFY ID)
    print("Loading Popolo data for Senedd ID conversion...")
    popolo = Popolo.from_parlparse()

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

        en_appg, cy_appg = process_cpg(body_id, name, popolo=popolo)

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
