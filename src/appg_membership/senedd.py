from __future__ import annotations

import re
from datetime import date
from html import unescape
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urljoin

import httpx
from mysoc_validator import Popolo
from mysoc_validator.models.popolo import IdentifierScheme
from pydantic import HttpUrl

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
from .senedd_lifecycle import (
    SENEDD_TERMS,
    SeneddMembershipChecker,
    archive_group,
    bound_senedd_group,
    membership_is_current,
)
from .senedd_models import MembershipValidity, SeneddRegistration

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


def clean_member_name(name: str, has_senedd_id: bool) -> str:
    """
    Clean a member name by normalizing whitespace and stripping
    the " MS" or " AS" suffix for Senedd members.
    """
    # Normalize excess whitespace
    name = re.sub(r"\s+", " ", unescape(name)).strip()
    # Strip trailing " MS" or " AS" for parliamentary members
    if has_senedd_id:
        name = re.sub(r"\s+(?:MS|AS)$", "", name)
    return name


def parse_members_list(html: str) -> list[dict[str, str]]:
    """
    Parse the members list from a Senedd CPG detail page.

    The Senedd pages use a <ul class="mgBulletList"> with <li> items:
      <li><a href="mgUserInfo.aspx?UID=332">Mike Hedges MS</a> &#40;Chair&#41; </li>
    Roles are in HTML-encoded parentheses: &#40; = ( and &#41; = )

    Returns a list of dicts with 'name', 'role', and 'senedd_id' keys.
    The senedd_id is extracted from the mgUserInfo.aspx?UID=NNN link.
    Names have excess whitespace normalized and " MS"/" AS" suffixes stripped
    for parliamentary members (those with a senedd_id).
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

        # Clean name: normalize whitespace, strip MS/AS suffix for Senedd members
        name = clean_member_name(name, has_senedd_id=bool(senedd_id))

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


class CPGEntry(NamedTuple):
    """
    A source registration linked from the validated current-register section.
    """

    body_id: str
    name: str


class BilingualCPG(NamedTuple):
    """
    English and Welsh representations of the same registration and membership.
    """

    english: APPG
    welsh: APPG


def parse_current_cpg_list(html: str) -> list[CPGEntry]:
    """
    Recognise a complete current register, including a confirmed empty list.

    Unknown layouts and error pages raise rather than closing saved registrations.
    Archived links elsewhere on the page cannot become current registrations.
    """
    match = re.search(
        r"<h2[^>]*>\s*Current Cross-Party Groups\s*</h2>\s*"
        r'<ul\s+class="mgBulletList"[^>]*>(.*?)</ul>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise ValueError("Unrecognised Senedd current register; saved data retained")
    section = match.group(1)
    entries = [CPGEntry(item["id"], item["name"]) for item in parse_cpg_list(section)]
    if not entries and clean_html_text(section):
        raise ValueError("Unrecognised empty register; saved data retained")
    if len(re.findall(r"<li\b", section, re.IGNORECASE)) != len(entries):
        raise ValueError("Incomplete Senedd register parsing; saved data retained")
    if len({entry.body_id for entry in entries}) != len(entries):
        raise ValueError("Duplicate source IDs in Senedd current register")
    slugs = [create_slug_from_name(entry.name) for entry in entries]
    if len(set(slugs)) != len(slugs):
        raise ValueError("Ambiguous names in Senedd current register")
    return entries


def validate_current_detail(html: str) -> None:
    """
    Reject archives, error pages and incomplete detail pages before changing data.
    """
    title = re.search(r'<h2[^>]*class="mgSubTitleTxt"[^>]*>(.*?)</h2>', html, re.S)
    text = clean_html_text(html)
    member_section = re.search(
        r"<h2[^>]*>(?:Members|Aelodau)</h2>\s*"
        r'<ul\s+class="mgBulletList"[^>]*>(.*?)</ul>',
        html,
        re.S | re.I,
    )
    if not title or not member_section:
        raise ValueError("Unrecognised Senedd detail page; saved data retained")
    if len(re.findall(r"<li\b", member_section.group(1), re.I)) != len(
        parse_members_list(html)
    ):
        raise ValueError("Incomplete Senedd membership list; saved data retained")
    if re.search(
        r"Sixth Senedd|Chweched Senedd|was dissolved|wedi.*ddiddymu", text, re.I
    ):
        raise ValueError("Archived Senedd registration cannot be imported as current")


def process_cpg(
    body_id: str,
    en_name: str,
    popolo: Popolo | None = None,
    registration: SeneddRegistration | None = None,
    observed_on: date | None = None,
) -> BilingualCPG:
    """
    Fetch a complete bilingual registration, failing before saving partial results.
    """
    observed_on = observed_on or date.today()
    en_url = urljoin(SENEDD_EN_BASE, DETAIL_PAGE.format(body_id=body_id))
    cy_url = urljoin(SENEDD_CY_BASE, DETAIL_PAGE.format(body_id=body_id))
    en_html = fetch_page(en_url)
    cy_html = fetch_page(cy_url)
    validate_current_detail(en_html)
    validate_current_detail(cy_html)
    officers: list[Officer] = []
    members: list[Member] = []
    for data in parse_members_list(en_html):
        senedd_id = data["senedd_id"]
        twfy_id = lookup_twfy_id(senedd_id, popolo)
        validity = MembershipValidity(observed_on=observed_on)
        if determine_officer_role(data["role"]):
            officers.append(
                Officer(
                    role=data["role"],
                    name=data["name"],
                    party="",
                    mnis_id=senedd_id or None,
                    twfy_id=twfy_id,
                    validity=validity,
                )
            )
        else:
            members.append(
                Member(
                    name=data["name"],
                    member_type="ms"
                    if senedd_id
                    or re.search(r"\b(?:MS|AS)(?:\s*\([^)]*\))?$", data["name"])
                    else "other",
                    mnis_id=senedd_id or None,
                    twfy_id=twfy_id,
                    validity=validity,
                )
            )
    english = APPG(
        slug=create_slug_from_name(en_name),
        title=parse_detail_page_title(en_html) or en_name,
        purpose=parse_detail_page_purpose(en_html),
        parliament=Parliament.SENEDD_EN,
        officers=officers,
        members_list=MemberList(
            source_method="official",
            source_url=[HttpUrl(en_url)],
            last_updated=observed_on,
            members=members,
        ),
        contact_details=ContactDetails(
            website=WebsiteSource(status="register", url=HttpUrl(en_url))
        ),
        source_url=HttpUrl(en_url),
        senedd_registration=registration,
    )
    welsh = english.model_copy(deep=True)
    welsh.title = parse_detail_page_title(cy_html) or en_name
    welsh.purpose = parse_detail_page_purpose(cy_html)
    welsh.parliament = Parliament.SENEDD_CY
    welsh.source_url = HttpUrl(cy_url)
    welsh.members_list.source_url = [HttpUrl(cy_url)]
    welsh.contact_details.website.url = HttpUrl(cy_url)
    return BilingualCPG(english, welsh)


def save_appg(appg: APPG, data_dir: Path) -> None:
    """
    Save a registration while retaining existing category assignments.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / f"{appg.slug}.json"
    if file_path.exists() and not appg.categories:
        existing = APPG.model_validate_json(file_path.read_text(encoding="utf-8"))
        appg.categories = existing.categories
    file_path.write_text(appg.model_dump_json(indent=2) + "\n", encoding="utf-8")


def member_identity(member: Member | Officer) -> str:
    """
    Match membership evidence across snapshots without depending on language.
    """
    return member.twfy_id or member.mnis_id or member.name.casefold()


def reconcile_snapshot(
    previous: APPG,
    current: APPG | None,
    checker: SeneddMembershipChecker,
    observed_on: date,
    data_dir: Path,
) -> None:
    """
    Preserve prior evidence and end missing memberships at the observation bound.
    """
    previous = bound_senedd_group(previous, checker)
    old_registration = previous.senedd_registration
    new_registration = current.senedd_registration if current else None
    same_registration = bool(
        old_registration
        and new_registration
        and old_registration.id == new_registration.id
    )
    if same_registration and current and new_registration and old_registration:
        new_registration.observed_on = old_registration.observed_on or observed_on
        new_people = {
            member_identity(member): member
            for member in [*current.officers, *current.members_list.members]
        }
        for old_member in [*previous.officers, *previous.members_list.members]:
            new_member = new_people.get(member_identity(old_member))
            if new_member and membership_is_current(
                old_member, previous, checker, observed_on
            ):
                new_member.validity = (
                    old_member.validity.model_copy()
                    if old_member.validity
                    else MembershipValidity()
                )
                new_member.validity.observed_on = (
                    new_member.validity.observed_on or observed_on
                )
            elif new_member is None:
                validity = old_member.validity or MembershipValidity()
                if validity.valid_until is None or observed_on < validity.valid_until:
                    validity.valid_until = observed_on
                    validity.end_reason = "no_longer_listed"
                old_member.validity = validity
    elif old_registration:
        if (
            old_registration.valid_until is None
            or observed_on < old_registration.valid_until
        ):
            old_registration.valid_until = observed_on
            old_registration.end_reason = "no_longer_listed"
        previous = bound_senedd_group(previous, checker)
    archive_group(previous, data_dir)
    if current is None:
        save_appg(previous, data_dir / APPG._get_parliament_folder(previous.parliament))


def download_and_convert_senedd_data(
    data_dir: Path | None = None,
    observed_on: date | None = None,
    term_number: int = 7,
    classify_new_groups: bool = True,
) -> None:
    """
    Stage and validate a complete current register before reconciling saved data.

    The configured term is explicit, never inferred from the year of a scrape.
    A known term end remains enforced by the exporter even if this refresh fails.
    """
    data_dir = data_dir or Path(__file__).resolve().parents[2] / "data"
    observed_on = observed_on or date.today()
    term = SENEDD_TERMS[term_number]
    if observed_on < term.registration_opens_on or (
        term.ends_on and observed_on >= term.ends_on
    ):
        raise ValueError("Current register is not valid for the configured Senedd term")
    list_url = urljoin(SENEDD_EN_BASE, LIST_PAGE)
    entries = parse_current_cpg_list(fetch_page(list_url))
    popolo = Popolo.from_parlparse()
    checker = SeneddMembershipChecker(popolo)
    staged: list[APPG] = []
    for entry in entries:
        print(f"Processing: {entry.name} (ID: {entry.body_id})")
        registration = SeneddRegistration(
            body_id=entry.body_id,
            term=term_number,
            verified=True,
            evidence_url=HttpUrl(list_url),
            observed_on=observed_on,
        )
        pair = process_cpg(
            entry.body_id,
            entry.name,
            popolo=popolo,
            registration=registration,
            observed_on=observed_on,
        )
        staged.extend(pair)

    # No saved files change until every English and Welsh detail page is valid.
    for parliament in (Parliament.SENEDD_EN, Parliament.SENEDD_CY):
        folder = data_dir / APPG._get_parliament_folder(parliament)
        previous = [
            APPG.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(folder.glob("*.json"))
        ]
        current_groups = [group for group in staged if group.parliament == parliament]
        current_by_id = {
            group.senedd_registration.id: group
            for group in current_groups
            if group.senedd_registration
        }
        for old in previous:
            registration = old.senedd_registration
            current = current_by_id.get(registration.id) if registration else None
            reconcile_snapshot(old, current, checker, observed_on, data_dir)
        for group in current_groups:
            save_appg(bound_senedd_group(group, checker), folder)
        if classify_new_groups:
            assign_categories_for_new_groups(
                parliament=parliament,
                previous_slugs={group.slug for group in previous},
                current_slugs={group.slug for group in current_groups},
            )
    print(f"Saved {len(entries)} current bilingual Senedd registrations")
