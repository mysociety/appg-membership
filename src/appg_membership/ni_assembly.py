import json
import re
from html import unescape
from pathlib import Path

import httpx
from mysoc_validator import Popolo
from mysoc_validator.models.popolo import IdentifierScheme
from pydantic import AliasGenerator, BaseModel, ConfigDict, HttpUrl
from pydantic.alias_generators import to_pascal

from .category_assignment import assign_categories_for_new_groups
from .models import (
    APPG,
    ContactDetails,
    Member,
    MemberList,
    Officer,
    Parliament,
    WebsiteSource,
)

# API endpoints
ORGANISATIONS_URL = (
    "https://data.niassembly.gov.uk/organisations.asmx/"
    "GetAllPartyGroupsListCurrent_JSON"
)
MEMBER_ROLES_URL = "https://data.niassembly.gov.uk/members.asmx/GetAllMemberRoles_JSON"
DETAIL_PAGE_URL = "https://aims.niassembly.gov.uk/mlas/apgdetails.aspx?&cid={org_id}"


# --- Pydantic models for NI Assembly API responses ---


class PascalModel(BaseModel):
    """Base model that converts snake_case field names to PascalCase aliases."""

    model_config = ConfigDict(
        alias_generator=AliasGenerator(validation_alias=to_pascal),
    )


class NIOrganisation(PascalModel):
    """A single NI Assembly All-Party Group organisation."""

    organisation_id: str
    organisation_name: str
    organisation_type: str


class NIOrganisationsList(PascalModel):
    """Wrapper for the list of organisations."""

    organisation: list[NIOrganisation]


class NIOrganisationsResponse(PascalModel):
    """Top-level response from GetAllPartyGroupsListCurrent_JSON."""

    organisations_list: NIOrganisationsList


class NIMemberRole(PascalModel):
    """A single member role from the NI Assembly API."""

    person_id: str
    affiliation_id: str
    member_full_display_name: str
    role_type: str
    role: str
    organisation_id: str
    organisation: str
    affiliation_start: str
    affiliation_title: str


class NIAllMembersRoles(PascalModel):
    """Wrapper for all member roles."""

    role: list[NIMemberRole]


class NIAllMembersRolesResponse(PascalModel):
    """Top-level response from GetAllMemberRoles_JSON."""

    all_members_roles: NIAllMembersRoles


# --- Helper functions ---


def create_slug_from_name(name: str) -> str:
    """
    Convert an NI Assembly All-Party Group name to a slug.
    E.g. 'All-Party Group on Access to Justice' -> 'access-to-justice'
    """
    # Remove the standard prefix
    clean_name = re.sub(
        r"^All-Party Group on\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # Remove leading "the " from the topic name
    clean_name = re.sub(r"^the\s+", "", clean_name, flags=re.IGNORECASE)

    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^\w\s-]", "", clean_name.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    slug = slug.strip("-")

    return slug


def determine_officer_role(role: str) -> bool:
    """
    Determine if an NI Assembly APG role is an officer role.
    """
    officer_roles = [
        "assembly party group chairperson",
        "assembly party group vice-chairperson",
        "assembly party group secretary",
        "assembly party group treasurer",
    ]
    return role.lower().strip() in officer_roles


def normalise_role_name(role: str) -> str:
    """
    Convert an NI Assembly role title to a shorter display name.
    E.g. 'Assembly Party Group Chairperson' -> 'Chairperson'
    """
    return re.sub(
        r"^Assembly Party Group\s+",
        "",
        role,
        flags=re.IGNORECASE,
    ).strip()


def lookup_twfy_id(person_id: str, popolo: Popolo | None) -> str | None:
    """
    Look up a TWFY person ID from an NI Assembly person ID using the Popolo dataset.

    Returns the TWFY person ID string (e.g. 'uk.org.publicwhip/person/...')
    or None if not found.
    """
    if not popolo or not person_id:
        return None

    try:
        person = popolo.persons.from_identifier(
            person_id, scheme=IdentifierScheme.NI_ASSEMBLY
        )
        return person.id
    except (KeyError, ValueError):
        return None


def fetch_organisations() -> list[NIOrganisation]:
    """
    Fetch the list of current NI Assembly All-Party Groups using a POST request.
    """
    response = httpx.post(ORGANISATIONS_URL, timeout=30)
    response.raise_for_status()
    data = response.json()
    parsed = NIOrganisationsResponse.model_validate(data)
    return parsed.organisations_list.organisation


def fetch_member_roles() -> list[NIMemberRole]:
    """
    Fetch all member roles from the NI Assembly API using a POST request.
    """
    response = httpx.post(MEMBER_ROLES_URL, timeout=30)
    response.raise_for_status()
    data = response.json()
    parsed = NIAllMembersRolesResponse.model_validate(data)
    return parsed.all_members_roles.role


def _clean_html_to_text(html_fragment: str) -> str:
    """Convert an HTML fragment to plain text, excluding scripts/styles."""
    text = re.sub(
        r"<script[^>]*>.*?</script>",
        " ",
        html_fragment,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(
        r"<noscript[^>]*>.*?</noscript>", " ", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def scrape_purpose_from_detail_page(html: str) -> str | None:
    """
    Extract the purpose text from an NI Assembly APG detail page.
    Looks for the 'Purpose' accordion section.
    """
    synopsis_match = re.search(
        r'<div[^>]*class="[^"]*synopsis[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if synopsis_match:
        text = _clean_html_to_text(synopsis_match.group(1))
        text = re.sub(r"^Purpose\s*:\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*•\s*", "; ", text)
        text = re.sub(r"^;\s*", "", text)
        text = re.sub(r"\.\s*;", ";", text)
        text = re.sub(r"\s*;\s*", "; ", text).strip()
        if text:
            return text

    # Fallback for older or variant pages where purpose may appear in accordion pane 0.
    pane_match = re.search(
        r'id="ctl00_MainContentPlaceHolder_AccordionPane0_content"[^>]*>(.*?)'
        r'(?=<div[^>]*id="ctl00_MainContentPlaceHolder_AccordionPane[1-9]_header"|$)',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if pane_match:
        text = _clean_html_to_text(pane_match.group(1))
        text = re.sub(r"\s*•\s*", "; ", text)
        text = re.sub(r"^;\s*", "", text)
        text = re.sub(r"\.\s*;", ";", text)
        text = re.sub(r"\s*;\s*", "; ", text).strip()
        if text:
            return text

    return None


def scrape_benefits_from_detail_page(html: str) -> str | None:
    """
    Extract the financial or other benefits text from an NI Assembly APG detail page.
    Looks for the 'Financial or Other Benefits Received' accordion section.
    """
    # First preference: extract the finance table only to avoid footer/script leakage.
    table_match = re.search(
        r'<table[^>]*id="ctl00_MainContentPlaceHolder_AccordionPane1_content_APGFinanceGridView"[^>]*>(.*?)</table>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if table_match:
        text = _clean_html_to_text(table_match.group(1))
        return text if text else None

    # Fallback: explicit no-finance message shown for some groups.
    no_finance_match = re.search(
        r"There have been no financial or other benefits received by this committee",
        html,
        re.IGNORECASE,
    )
    if no_finance_match:
        return no_finance_match.group(0)

    # Last fallback: limited pane extraction without scripts/styles.
    benefits_match = re.search(
        r'id="ctl00_MainContentPlaceHolder_AccordionPane1_content"[^>]*>(.*?)'
        r"(?=<script|</main>|</form>|</body>|$)",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if benefits_match:
        text = _clean_html_to_text(benefits_match.group(1))
        if text:
            return text

    return None


def fetch_detail_page(org_id: str) -> str | None:
    """
    Fetch the detail page for an NI Assembly APG using a POST request to trigger
    the ASPX page content.
    """
    url = DETAIL_PAGE_URL.format(org_id=org_id)
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        return response.text
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"  Warning: Could not fetch detail page for org {org_id}: {e}")
        return None


def download_and_convert_ni_data():
    """
    Download NI Assembly All-Party Group data and convert to APPG format.

    This function:
    1. Fetches current All-Party Groups from the NI Assembly API
    2. Fetches all member roles and filters to APG roles
    3. Uses the Popolo library for TWFY ID lookups
    4. Scrapes purpose and financial benefits from detail pages
    5. Saves one JSON file per group in data/apg_ni/
    """
    data_dir = Path(__file__).parent.parent.parent / "data" / "apg_ni"
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {data_dir}")
    existing_slugs = {path.stem for path in data_dir.glob("*.json")}

    # Initialize Popolo for person lookup
    print("Loading Popolo data for NI Assembly ID conversion...")
    popolo = Popolo.from_parlparse()

    # Fetch all the data
    print("Fetching NI Assembly All-Party Groups...")
    organisations = fetch_organisations()
    print(f"Found {len(organisations)} All-Party Groups")

    print("Fetching member roles...")
    all_roles = fetch_member_roles()

    # Filter to only APG roles
    apg_roles = [r for r in all_roles if r.role_type == "All Party Group Role"]
    print(f"Found {len(apg_roles)} All-Party Group role assignments")

    # Group APG roles by organisation ID
    roles_by_org: dict[str, list[NIMemberRole]] = {}
    for role in apg_roles:
        if role.organisation_id not in roles_by_org:
            roles_by_org[role.organisation_id] = []
        roles_by_org[role.organisation_id].append(role)

    # Process each organisation
    for org in organisations:
        print(f"Processing: {org.organisation_name}")

        slug = create_slug_from_name(org.organisation_name)
        org_roles = roles_by_org.get(org.organisation_id, [])

        # Scrape purpose and benefits from detail page
        purpose = None
        benefits = None
        detail_html = fetch_detail_page(org.organisation_id)
        if detail_html:
            purpose = scrape_purpose_from_detail_page(detail_html)
            benefits = scrape_benefits_from_detail_page(detail_html)

        # Convert members - deduplicate by person_id, preferring officer roles
        seen_persons: dict[str, NIMemberRole] = {}
        for role in org_roles:
            existing = seen_persons.get(role.person_id)
            if existing is None:
                seen_persons[role.person_id] = role
            elif determine_officer_role(role.role) and not determine_officer_role(
                existing.role
            ):
                # Prefer officer role over member role
                seen_persons[role.person_id] = role

        officers = []
        member_list = []
        for role in seen_persons.values():
            name = role.member_full_display_name
            is_officer = determine_officer_role(role.role)
            twfy_id = lookup_twfy_id(role.person_id, popolo)
            member_type = "mla" if twfy_id else "other"

            if is_officer:
                officers.append(
                    Officer(
                        role=normalise_role_name(role.role),
                        name=name,
                        party="",
                        twfy_id=twfy_id,
                        mnis_id=role.person_id,
                    )
                )
            else:
                member_list.append(
                    Member(
                        name=name,
                        is_officer=False,
                        member_type=member_type,
                        twfy_id=twfy_id,
                        mnis_id=role.person_id,
                    )
                )

        detail_url = DETAIL_PAGE_URL.format(org_id=org.organisation_id)

        appg = APPG(
            slug=slug,
            title=org.organisation_name,
            purpose=purpose,
            category=None,
            parliament=Parliament.NI,
            officers=officers,
            members_list=MemberList(
                source_method="official",
                source_url=[HttpUrl(detail_url)],
                last_updated=None,
                members=member_list,
            ),
            contact_details=ContactDetails(
                website=WebsiteSource(status="register", url=HttpUrl(detail_url))
            ),
            agm=None,
            registrable_benefits=benefits,
            detailed_benefits=[],
            index_date="",
            source_url=HttpUrl(detail_url),
            categories=[],
        )

        # Save to file
        file_path = data_dir / f"{slug}.json"
        if file_path.exists() and not appg.categories:
            with file_path.open("r", encoding="utf-8") as existing_file:
                existing_appg = APPG.model_validate_json(existing_file.read())
            appg.categories = existing_appg.categories

        with file_path.open("w", encoding="utf-8") as f:
            json.dump(
                appg.model_dump(mode="json", exclude_none=False),
                f,
                indent=2,
                ensure_ascii=False,
            )

        print(
            f"  Saved: {file_path} ({len(officers)} officers, {len(member_list)} members)"
        )

    print(f"\nCompleted processing {len(organisations)} All-Party Groups")
    print(f"Files saved to: {data_dir}")

    current_slugs = {path.stem for path in data_dir.glob("*.json")}
    assigned_count = assign_categories_for_new_groups(
        parliament=Parliament.NI,
        previous_slugs=existing_slugs,
        current_slugs=current_slugs,
    )
    if assigned_count:
        print(f"Assigned categories for {assigned_count} new NI groups")
