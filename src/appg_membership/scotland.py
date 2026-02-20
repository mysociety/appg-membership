import json
import re
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import httpx
from mysoc_validator import Popolo
from mysoc_validator.models.popolo import IdentifierScheme
from pydantic import AliasGenerator, BaseModel, ConfigDict, HttpUrl, TypeAdapter
from pydantic.alias_generators import to_pascal as base_pascal
from pydantic_store import JsonStore
from typing_extensions import Self

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


def to_pascal(name: str) -> str:
    first_round = base_pascal(name)
    return first_round.replace("Id", "ID")


def create_slug_from_name(name: str) -> str:
    """
    Convert a Cross-Party Group name to a slug.
    E.g. 'Cross-Party Group in the Scottish Parliament on Epilepsy' -> 'epilepsy'
    """
    # Remove the standard prefix
    clean_name = re.sub(
        r"^Cross-Party Group in the Scottish Parliament on\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # Remove leading "the " from the topic name for URL compatibility
    clean_name = re.sub(r"^the\s+", "", clean_name, flags=re.IGNORECASE)

    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^\w\s-]", "", clean_name.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    slug = slug.strip("-")

    return slug


def scrape_purpose_from_url(url: str) -> str | None:
    """
    Scrape the purpose from a Cross-Party Group's public URL.
    Uses a robust approach: find the 'purpose' marker, then extract all content
    from the parent container, handling various formats (p, ul, div, etc.).
    """
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()

        html = response.text

        # Find the purpose marker and extract the parent container's content
        # This handles all variations: separate <p>, inline <p>, <ul> lists, etc.

        # First, try to find the rich-text div containing the purpose
        rich_text_pattern = r'<div[^>]*class="rich-text"[^>]*>(.*?)</div>'
        rich_text_match = re.search(rich_text_pattern, html, re.DOTALL | re.IGNORECASE)

        if rich_text_match:
            rich_text_content = rich_text_match.group(1)

            # Try different patterns for extracting purpose content

            # Pattern 1: Purpose marker followed by content in next <p> element
            # e.g., <p>This Cross-party group's purpose:</p><p><span>content</span></p>
            next_p_pattern = (
                r"<p[^>]*>\s*This Cross-party group\'s purpose:\s*(?:&nbsp;)?\s*</p>\s*"
                r"<p[^>]*>(.*?)</p>"
            )
            next_p_match = re.search(
                next_p_pattern, rich_text_content, re.DOTALL | re.IGNORECASE
            )
            if next_p_match:
                purpose_content = next_p_match.group(1)
                purpose_text = re.sub(r"<[^>]+>", "", purpose_content)
                purpose_text = re.sub(r"\s+", " ", purpose_text).strip()
                purpose_text = re.sub(r"&nbsp;", " ", purpose_text)
                purpose_text = re.sub(r"&rsquo;", "'", purpose_text)
                purpose_text = re.sub(r"&ldquo;", '"', purpose_text)
                purpose_text = re.sub(r"&rdquo;", '"', purpose_text)
                if purpose_text:
                    return purpose_text

            # Pattern 2: Purpose marker followed by <ul> list
            # e.g., <p>This Cross-party group's purpose:</p><ul><li>content</li></ul>
            ul_pattern = (
                r"<p[^>]*>\s*This Cross-party group\'s purpose:\s*(?:&nbsp;)?\s*</p>\s*"
                r"<ul[^>]*>(.*?)</ul>"
            )
            ul_match = re.search(
                ul_pattern, rich_text_content, re.DOTALL | re.IGNORECASE
            )
            if ul_match:
                purpose_content = ul_match.group(1)
                purpose_text = re.sub(r"<[^>]+>", "", purpose_content)
                purpose_text = re.sub(r"\s+", " ", purpose_text).strip()
                purpose_text = re.sub(r"&nbsp;", " ", purpose_text)
                purpose_text = re.sub(r"&rsquo;", "'", purpose_text)
                purpose_text = re.sub(r"&ldquo;", '"', purpose_text)
                purpose_text = re.sub(r"&rdquo;", '"', purpose_text)
                if purpose_text:
                    return purpose_text

            # Pattern 3: Purpose marker with content inline after <br/>
            # e.g., <p>This Cross-party group's purpose:<br/>content</p>
            inline_pattern = r"<p[^>]*>\s*This Cross-party group\'s purpose:\s*(?:&nbsp;)?\s*<br\s*/?>\s*(.*?)</p>"
            inline_match = re.search(
                inline_pattern, rich_text_content, re.DOTALL | re.IGNORECASE
            )
            if inline_match:
                purpose_content = inline_match.group(1)
                purpose_text = re.sub(r"<[^>]+>", "", purpose_content)
                purpose_text = re.sub(r"\s+", " ", purpose_text).strip()
                purpose_text = re.sub(r"&nbsp;", " ", purpose_text)
                purpose_text = re.sub(r"&rsquo;", "'", purpose_text)
                purpose_text = re.sub(r"&ldquo;", '"', purpose_text)
                purpose_text = re.sub(r"&rdquo;", '"', purpose_text)
                if purpose_text:
                    return purpose_text

        # Fallback: try the old pattern in case rich-text div is not found
        purpose_pattern = (
            r'<div[^>]*class="rich-text"[^>]*>(.*?)'
            r"<p[^>]*>\s*This Cross-party group\'s purpose:\s*(?:&nbsp;)?\s*(?:</p>|<br\s*/?>\s*)"
            r"(.*?)"
            r"</div>"
        )

        match = re.search(purpose_pattern, html, re.DOTALL | re.IGNORECASE)

        if match:
            # Extract everything after the purpose marker within the rich-text div
            purpose_content = match.group(2)

            # Clean up HTML tags and normalize whitespace
            purpose_text = re.sub(r"<[^>]+>", "", purpose_content)
            purpose_text = re.sub(r"\s+", " ", purpose_text).strip()
            purpose_text = re.sub(r"&nbsp;", " ", purpose_text)
            purpose_text = re.sub(r"&rsquo;", "'", purpose_text)
            purpose_text = re.sub(r"&ldquo;", '"', purpose_text)
            purpose_text = re.sub(r"&rdquo;", '"', purpose_text)

            if purpose_text:
                return purpose_text

        return None

    except (httpx.RequestError, httpx.HTTPStatusError, Exception) as e:
        print(f"Warning: Could not scrape purpose from {url}: {e}")
        return None


class PascalModel(BaseModel):
    source_url: ClassVar[str] = ""
    model_config = ConfigDict(
        alias_generator=AliasGenerator(validation_alias=to_pascal), extra="forbid"
    )

    @classmethod
    def fetch_data(cls) -> list[Self]:
        response = httpx.get(cls.source_url)
        response.raise_for_status()
        data = response.json()
        adapter = TypeAdapter(list[cls])
        return adapter.validate_python(data)


class CrossPartyGroup(PascalModel):
    source_url: ClassVar[str] = "https://data.parliament.scot/api/crosspartygroups/json"
    id: int
    name: str
    gaelic_name: str | None
    description: str | None
    valid_from_date: datetime
    valid_until_date: datetime | None

    def get_public_url(self) -> str:
        """
        Generate the public URL for this Cross-Party Group.
        Format: https://www.parliament.scot/get-involved/cross-party-groups/current-cross-party-groups/{year}/{slug}
        Uses the year from the valid_from_date field, with corrections for known exceptions.
        """
        slug = create_slug_from_name(self.name)
        year = self.valid_from_date.year

        # Handle known URL year exceptions where API date doesn't match working URL
        year_corrections = {
            "space": 2023,  # API says 2022, but URL is 2023
        }

        if slug in year_corrections:
            year = year_corrections[slug]

        return f"https://www.parliament.scot/get-involved/cross-party-groups/current-cross-party-groups/{year}/{slug}"


class CrossPartyGroupRole(PascalModel):
    source_url: ClassVar[str] = (
        "https://data.parliament.scot/api/crosspartygrouproles/json"
    )
    id: int
    name: str
    notes: str | None


class CrossPartyGroupMember(PascalModel):
    source_url: ClassVar[str] = (
        "https://data.parliament.scot/api/membercrosspartyroles/json"
    )
    id: int
    person_id: int
    cross_party_group_role_id: int
    cross_party_group_id: int
    valid_from_date: datetime
    valid_until_date: datetime | None


def get_group_purpose(
    group: CrossPartyGroup, cache: JsonStore[str]
) -> tuple[str | None, bool]:
    """
    Get the purpose for a group, using cache first, then scraping if needed.
    Returns (purpose, cache_updated) tuple.
    """
    slug = create_slug_from_name(group.name)

    # Check cache first
    if slug in cache:
        if cache[slug]:
            return cache[slug], False

    # Not in cache, try to scrape
    print(f"  Scraping purpose for {group.name}...")
    public_url = group.get_public_url()
    purpose = scrape_purpose_from_url(public_url)

    if purpose:
        cache[slug] = purpose
        return purpose, True
    else:
        # Store empty string to avoid re-scraping failed attempts
        cache[slug] = ""
        return None, True


def download_and_convert_scotland_data():
    """
    Download Scotland Cross-Party Group data and convert to APPG format.

    This function:
    1. Fetches current Cross-Party Groups (those with null valid_until_date)
    2. Fetches current member roles and membership data
    3. Converts member data to APPG format using the Popolo library for person lookups
    4. Generates public URLs for each group
    5. Saves one JSON file per group in data/cpg_scotland/

    The generated files follow the same format as UK APPGs for consistency.
    """

    # Get the data directory
    data_dir = Path(__file__).parent.parent.parent / "data" / "cpg_scotland"
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {data_dir}")
    existing_slugs = {path.stem for path in data_dir.glob("*.json")}

    # Initialize Popolo for person lookup
    popolo = Popolo.from_parlparse()

    # Fetch all the data
    print("Fetching Cross-Party Groups...")
    groups = CrossPartyGroup.fetch_data()

    print("Fetching roles...")
    roles = CrossPartyGroupRole.fetch_data()

    print("Fetching members...")
    members = CrossPartyGroupMember.fetch_data()

    # Create lookup dictionaries
    role_lookup = {role.id: role for role in roles}

    # Filter to only current groups (null valid_until_date)
    current_groups = [group for group in groups if group.valid_until_date is None]
    print(f"Found {len(current_groups)} current Cross-Party Groups")

    # Load purpose cache
    print("Loading purpose cache...")
    purpose_cache = JsonStore[str].connect(
        Path("data", "raw", "scotland_purposes.json")
    )

    # Group members by group_id
    members_by_group = {}
    for member in members:
        if member.valid_until_date is None:  # Only current members
            if member.cross_party_group_id not in members_by_group:
                members_by_group[member.cross_party_group_id] = []
            members_by_group[member.cross_party_group_id].append(member)

    # Process each group
    for group in current_groups:
        print(f"Processing: {group.name}")

        # Create slug
        slug = create_slug_from_name(group.name)

        # Get members for this group
        group_members = members_by_group.get(group.id, [])

        # Skip groups with no members (assume defunct)
        if not group_members:
            print(f"  Skipping {group.name} - no members found (assumed defunct)")
            continue

        # Convert members to officers and members list
        officers = []
        member_list = []

        for member in group_members:
            role = role_lookup.get(member.cross_party_group_role_id)
            role_name = role.name if role else "Member"

            # Try to get person details from popolo
            person_obj = None
            try:
                person_obj = popolo.persons.from_identifier(
                    str(member.person_id), scheme=IdentifierScheme.SCOTPARL
                )
            except (KeyError, ValueError):
                print(
                    f"  Warning: Could not find person with ScotParl ID {member.person_id}"
                )
                continue

            if not person_obj:
                continue

            # Get person name
            person_name = ""
            if person_obj.names:
                person_name = person_obj.names[0].nice_name()
            else:
                print(f"  Warning: Could not get name for person {member.person_id}")
                continue

            # Get TWFY ID from person object ID and other IDs from identifiers
            twfy_id = person_obj.id  # The person object ID is the TWFY ID
            mnis_id = None

            # Get additional IDs from identifiers
            for identifier in person_obj.identifiers:
                if identifier.scheme == "datadotparl_id":
                    mnis_id = str(identifier.identifier)

            # Determine member type based on whether we have a TWFY ID
            member_type = "msp" if twfy_id else "other"

            # Determine if this is an officer role
            is_officer = role_name.lower() in [
                "convener",
                "co-convener",
                "deputy convener",
                "secretary",
                "treasurer",
            ]

            if is_officer:
                # Add to officers list
                officer = Officer(
                    role=role_name,
                    name=person_name,
                    party="",  # Party info not available in Scotland API
                    twfy_id=twfy_id,
                    mnis_id=mnis_id,
                    removed=False,
                )
                officers.append(officer)
            else:
                # Add to members list
                member_obj = Member(
                    name=person_name,
                    is_officer=False,
                    member_type=member_type,
                    twfy_id=twfy_id,
                    mnis_id=mnis_id,
                    removed=False,
                )
                member_list.append(member_obj)

        # Get purpose from cache or scrape from website
        purpose, updated = get_group_purpose(group, purpose_cache)

        # Create APPG object
        appg = APPG(
            slug=slug,
            title=group.name,
            purpose=purpose,
            category=None,  # Would need categorization logic
            parliament=Parliament.SCOTLAND,
            officers=officers,
            members_list=MemberList(
                source_method="official",  # Official Scottish Parliament API
                source_url=[HttpUrl(group.source_url)] if group.source_url else [],
                last_updated=None,
                members=member_list,
            ),
            contact_details=ContactDetails(
                website=WebsiteSource(
                    status="register", url=HttpUrl(group.get_public_url())
                )
            ),
            agm=None,
            registrable_benefits=None,
            detailed_benefits=[],
            index_date="",
            source_url=HttpUrl(group.get_public_url()),
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
    print(f"\nCompleted processing {len(current_groups)} Cross-Party Groups")
    print(f"Files saved to: {data_dir}")

    current_slugs = {path.stem for path in data_dir.glob("*.json")}
    assigned_count = assign_categories_for_new_groups(
        parliament=Parliament.SCOTLAND,
        previous_slugs=existing_slugs,
        current_slugs=current_slugs,
    )
    if assigned_count:
        print(f"Assigned categories for {assigned_count} new Scotland groups")
