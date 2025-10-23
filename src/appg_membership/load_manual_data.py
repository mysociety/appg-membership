"""
Module for downloading and parsing manual APPG membership data from Google Docs.

This module handles downloading a Google Docs document as markdown and parsing it
to extract APPG membership information. The document structure is:
- H1: Ignored
- H2: APPG title
- H3: Either "notes" (ignored) or "members" (processed)
- If no H3s under H2, all content is treated as members
- Members are parsed as any line with content
"""

import re
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import httpx
from rich.console import Console

from appg_membership.models import APPG, Member

console = Console()

# Default URL for the Google Docs markdown export
DEFAULT_DOC_URL = "https://docs.google.com/document/d/1IzlRjxXyT8qmU3_-xLO3z_VmTnPIjkb1Hz6SFtkBnKs/export?format=markdown"

# Directory to store the downloaded markdown
MANUAL_DATA_DIR = Path("data", "raw", "manual")
MARKDOWN_FILE = MANUAL_DATA_DIR / "manual_membership.md"


def download_markdown(
    url: str = DEFAULT_DOC_URL, output_path: Path = MARKDOWN_FILE
) -> bool:
    """
    Download the Google Docs document as markdown.

    Args:
        url: URL to download the markdown from
        output_path: Path to save the markdown file

    Returns:
        True if successful, False otherwise
    """
    try:
        console.print(f"[blue]Downloading markdown from:[/blue] {url}")

        # Ensure directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Download the content (follow redirects)
        with httpx.Client(follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()

        # Save to file
        with output_path.open("w", encoding="utf-8") as f:
            f.write(response.text)

        console.print(f"[green]✓ Downloaded markdown to:[/green] {output_path}")
        return True

    except Exception as e:
        console.print(f"[red]✗ Failed to download markdown:[/red] {e}")
        return False


def parse_markdown_content(content: str) -> dict[str, list[str]]:
    """
    Parse the markdown content to extract APPG membership data.

    Structure:
    - H1: Ignored
    - H2: APPG title (becomes key)
    - H3: Either "notes" (ignored) or "members" (processed)
    - If no H3s under H2, all content is treated as members
    - Members are parsed as any line with content

    Args:
        content: The markdown content as a string

    Returns:
        Dictionary mapping APPG names to lists of member names
    """
    lines = content.split("\n")
    appg_data = {}
    current_appg = None
    current_section = None
    current_members = []

    for line in lines:
        line = line.strip()

        # Skip empty lines
        if not line:
            continue

        # Check for H1 (ignore)
        if line.startswith("# "):
            continue

        # Check for H2 (APPG title)
        elif line.startswith("## "):
            # Save previous APPG if it exists
            if current_appg and current_members:
                appg_data[current_appg] = current_members

            # Start new APPG - clean the title of markdown formatting
            raw_title = line[3:].strip()  # Remove '## '
            # Remove bold formatting
            current_appg = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw_title)
            current_section = None
            current_members = []

        # Check for H3 (section)
        elif line.startswith("### "):
            section_title = line[4:].strip().lower()  # Remove '### '

            if section_title == "notes":
                current_section = "notes"
            elif section_title == "members":
                current_section = "members"
            else:
                # Treat unknown H3s as members section
                current_section = "members"

        # Regular content
        else:
            # If we have an APPG but no H3 section, treat as members
            if current_appg and current_section is None:
                current_section = "members"

            # Only process content if we're in members section
            if current_appg and current_section == "members":
                # Clean up the line (remove markdown formatting, etc.)
                cleaned_line = clean_member_name(line)
                if cleaned_line:
                    current_members.append(cleaned_line)

    # Don't forget the last APPG
    if current_appg and current_members:
        appg_data[current_appg] = current_members

    return appg_data


def clean_member_name(line: str) -> Optional[str]:
    """
    Clean a line to extract a member name.

    Removes markdown formatting, bullet points, numbering, etc.

    Args:
        line: Raw line from markdown

    Returns:
        Cleaned member name or None if line doesn't contain a valid name
    """
    # Remove markdown formatting
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)  # Bold
    line = re.sub(r"\*([^*]+)\*", r"\1", line)  # Italic
    line = re.sub(r"`([^`]+)`", r"\1", line)  # Code

    # Remove bullet points and list markers
    line = re.sub(r"^[-*+]\s+", "", line)  # Unordered lists
    line = re.sub(r"^\d+\.\s+", "", line)  # Ordered lists
    line = re.sub(r"^\d+\\\.\s+", "", line)  # Escaped dots (Google Docs export)
    line = re.sub(r"^\\[-*+]\s+", "", line)  # Escaped bullet points (\-, \*, \+)

    # Remove pipe characters and clean up
    line = re.sub(r"^\|+\s*", "", line)  # Leading pipes
    line = re.sub(r"\s*\|+$", "", line)  # Trailing pipes
    line = re.sub(r"\|", "", line)  # Any remaining pipes

    # Replace tabs with spaces and normalize whitespace
    line = re.sub(r"\t", " ", line)  # Replace tabs with spaces
    while "  " in line:  # Recursively replace double spaces with single spaces
        line = line.replace("  ", " ")

    # Remove leading/trailing whitespace
    line = line.strip()

    # Skip generic terms that should be ignored entirely
    generic_terms = [
        "members",
        "members;",
        "membership",
        "officers:",
        "officers",
        "chair and officers",
        "chair:",
        "dep chair:",
        "honorary president:",
        "name organisation representing if applicable",
        "non-parliamentarians:",
        "donors",
        "external",
        ":----",
    ]
    if line.lower() in generic_terms:
        return None

    # Remove email addresses
    line = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "", line)

    # Remove role prefixes
    line = re.sub(r"^(member|officer)\s+", "", line, flags=re.IGNORECASE)
    line = re.sub(
        r"^(chair|vice[\s-]*chair|deputy[\s-]*chair|honorary[\s-]*president|dep\s+chair):\s*",
        "",
        line,
        flags=re.IGNORECASE,
    )

    # Remove constituency/commons information (pattern: "party commons constituency")
    line = re.sub(
        r"\s+(conservative|labour|liberal\s+democrat|libdem|snp|plaid\s+cymru|green|dup|independent)\s+commons\s+.*$",
        "",
        line,
        flags=re.IGNORECASE,
    )

    # Handle duplicated names and leading numbers
    words = line.split()
    if words:
        # Remove leading number if present
        if words[0].isdigit():
            words = words[1:]

        # Handle name duplications (e.g., "john whittingdale sir john whittingdale")
        if len(words) >= 4:
            # Alternative check: look for "firstname lastname firstname lastname" pattern
            if len(words) == 4:
                if (
                    words[0].lower() == words[2].lower()
                    and words[1].lower() == words[3].lower()
                ):
                    words = words[:2]  # Take first occurrence

            # Look for exact duplicated sequences
            half_len = len(words) // 2
            if half_len >= 2:
                first_half = words[:half_len]
                second_half = words[half_len:]

                # Check if we have exact name duplication
                if len(first_half) == len(second_half):
                    # Compare ignoring titles
                    title_words = [
                        "sir",
                        "dame",
                        "lord",
                        "lady",
                        "baroness",
                        "baron",
                        "mr",
                        "mrs",
                        "ms",
                        "miss",
                        "dr",
                    ]
                    first_names = [
                        w for w in first_half if w.lower() not in title_words
                    ]
                    second_names = [
                        w for w in second_half if w.lower() not in title_words
                    ]

                    if (
                        len(first_names) >= 2
                        and len(second_names) >= 2
                        and first_names[-1].lower() == second_names[-1].lower()
                        and first_names[-2].lower() == second_names[-2].lower()
                    ):
                        # We have a duplication - prefer the version with title
                        if any(w.lower() in title_words for w in second_half):
                            words = second_half
                        else:
                            words = first_half

            # Check for pattern: "firstname lastname title firstname lastname"
            if len(words) == 5:
                title_words = [
                    "sir",
                    "dame",
                    "lord",
                    "lady",
                    "baroness",
                    "baron",
                    "mr",
                    "mrs",
                    "ms",
                    "miss",
                    "dr",
                ]
                if (
                    words[2].lower() in title_words
                    and words[0].lower() == words[3].lower()
                    and words[1].lower() == words[4].lower()
                ):
                    words = words[2:]  # Take titled version

        line = " ".join(words)

    # Remove en-dash and em-dash role suffixes (e.g., "– vice chair", "— chair")
    line = re.sub(
        r"\s*[–—]\s*(vice[\s-]*chair|chair|officer|president).*$",
        "",
        line,
        flags=re.IGNORECASE,
    )

    # Remove parenthetical roles and trailing party abbreviations
    line = re.sub(
        r"\s*\((vice[\s-]*chair|chair|officer)\)\s*(lab|con|libdem|lib|snp|green|dup|independent|crossbench)?\s*$",
        "",
        line,
        flags=re.IGNORECASE,
    )

    # Remove standalone party names at the end (after whitespace)
    line = re.sub(
        r"\s+(lab|con|conservative|labour|libdem|liberal|democrat|snp|green|dup|independent|crossbench)\s*$",
        "",
        line,
        flags=re.IGNORECASE,
    )

    # Remove honorific prefixes like "the hon"
    line = re.sub(r"^(the\s+)?(rt\.?\s+)?(hon\.?\s+)", "", line, flags=re.IGNORECASE)

    # Handle additional duplication patterns after initial processing
    words = line.split()
    if len(words) >= 3:
        # Pattern: "name name" or "title name title name"
        if len(words) == 2 and words[0].lower() == words[1].lower():
            words = words[:1]  # Take single occurrence
        elif len(words) == 4:
            # Check for "title firstname lastname title firstname lastname"
            title_words = [
                "sir",
                "dame",
                "lord",
                "lady",
                "baroness",
                "baron",
                "mr",
                "mrs",
                "ms",
                "miss",
                "dr",
            ]
            if (
                words[0].lower() in title_words
                and words[2].lower() in title_words
                and words[1].lower() == words[3].lower()
            ):
                words = words[2:4]  # Take second occurrence (usually has better title)
        elif len(words) == 6:
            # Check for "firstname lastname title firstname lastname" or vice versa
            title_words = [
                "sir",
                "dame",
                "lord",
                "lady",
                "baroness",
                "baron",
                "mr",
                "mrs",
                "ms",
                "miss",
                "dr",
            ]
            if (
                len(words) >= 4
                and words[2].lower() in title_words
                and words[0].lower() == words[3].lower()
                and words[1].lower() == words[4].lower()
            ):
                words = words[2:5]  # Take titled version
            elif (
                len(words) >= 6
                and words[3].lower() in title_words
                and words[0].lower() == words[4].lower()
                and words[1].lower() == words[5].lower()
            ):
                words = words[3:6]  # Take titled version

    line = " ".join(words)

    # Replace tabs with spaces and normalize whitespace again
    line = re.sub(r"\t", " ", line)
    while "  " in line:
        line = line.replace("  ", " ")
    line = line.strip()

    # Handle "mp," pattern - extract name before "mp,"
    line_lower = line.lower()
    if "mp," in line_lower:
        # Find the position of "mp," and take everything before it + " MP"
        mp_pos = line_lower.find("mp,")
        if mp_pos > 0:
            line = line[:mp_pos].strip() + " MP"

    # Remove party names that appear after the name and title
    # For MPs: stop after 'MP' (everything after 'MP' is likely party info)
    if " MP " in line:
        line = line.split(" MP ")[0] + " MP"

    # For Lords and other titles: remove common party names at the end
    party_names = [
        "Labour",
        "Conservative",
        "Liberal Democrat",
        "Liberal Democrats",
        "LibDem",
        "SNP",
        "Plaid Cymru",
        "Green",
        "DUP",
        "Ulster Unionist",
        "SDLP",
        "Alliance",
        "Independent",
        "Crossbench",
        "Cross Bench",
        "Crossbencher",
        "Non-affiliated",
        "Sinn Fein",
        "Sinn Féin",
    ]

    # Create regex pattern to match party names at the end of the line
    party_pattern = (
        r"\s+(" + "|".join(re.escape(party) for party in party_names) + r")$"
    )
    line = re.sub(party_pattern, "", line, flags=re.IGNORECASE)

    # Skip if empty or looks like a header/non-name content
    if not line or line.startswith("#") or len(line) < 3:
        return None

    return line


def appg_title_to_slug(title: str) -> str:
    """
    Convert an APPG title to a slug format.

    Handles various APPG title formats and tries to match existing files.

    Args:
        title: APPG title

    Returns:
        Slug format
    """

    if title == "first-do-no-harm---mesh-primodos-valproate":
        return title

    # Remove common prefixes
    title_clean = title
    prefixes_to_remove = [
        "All-Party Parliamentary Group for",
        "All-Party Parliamentary Group on",
        "All-Party Parliamentary Group",
        "All Party-Parliamentary Group for",
        "All Party-Parliamentary Group on",
        "All Party-Parliamentary Group",
        "APPG for",
        "APPG on",
        "APPG",
    ]

    for prefix in prefixes_to_remove:
        if title_clean.startswith(prefix):
            title_clean = title_clean[len(prefix) :].strip()
            break

    # Remove common suffixes
    suffixes_to_remove = ["All-Party Parliamentary Group", "APPG", "APPG:"]

    for suffix in suffixes_to_remove:
        if title_clean.endswith(suffix):
            title_clean = title_clean[: -len(suffix)].strip()
            break

    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^\w\s-]", "", title_clean.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    slug = slug.strip("-")

    return slug


def find_matching_appg_file(title: str) -> Optional[str]:
    """
    Find the APPG file that matches the given title.

    Tries multiple strategies to find the correct file.

    Args:
        title: APPG title from markdown

    Returns:
        APPG slug if found, None otherwise
    """
    from pathlib import Path

    appg_dir = Path("data", "appgs")
    if not appg_dir.exists():
        return None

    # Strategy 1: Try the inferred slug directly
    inferred_slug = appg_title_to_slug(title)
    if (appg_dir / f"{inferred_slug}.json").exists():
        return inferred_slug

    # Strategy 2: Search through existing files for title matches
    for appg_file in appg_dir.glob("*.json"):
        try:
            with appg_file.open("r", encoding="utf-8") as f:
                import json

                data = json.load(f)

            # Check if the title matches (case insensitive, flexible)
            existing_title = data.get("title", "").lower()
            markdown_title = title.lower()

            # Remove common prefixes for comparison
            for prefix in [
                "all-party parliamentary group for",
                "all-party parliamentary group on",
                "all-party parliamentary group",
                "all party-parliamentary group for",
                "all party-parliamentary group on",
                "all party-parliamentary group",
                "appg for",
                "appg on",
                "appg",
            ]:
                if existing_title.startswith(prefix):
                    existing_title = existing_title[len(prefix) :].strip()
                if markdown_title.startswith(prefix):
                    markdown_title = markdown_title[len(prefix) :].strip()

            # Remove common suffixes for comparison
            for suffix in [
                "all-party parliamentary group",
                "appg",
            ]:
                if existing_title.endswith(suffix):
                    existing_title = existing_title[: -len(suffix)].strip()
                if markdown_title.endswith(suffix):
                    markdown_title = markdown_title[: -len(suffix)].strip()

            # Check for match
            if existing_title == markdown_title:
                return appg_file.stem

        except Exception:
            continue

    return None


def infer_member_type(name: str) -> Literal["mp", "lord", "other"]:
    """
    Infer the member type based on the name.

    Args:
        name: Member name

    Returns:
        Member type: 'mp', 'lord', or 'other'
    """
    name_lower = name.lower()

    # Check for MP suffix
    if " mp" in name_lower or name_lower.endswith(" mp"):
        return "mp"

    # Check for lord titles
    lord_titles = [
        "lord",
        "baroness",
        "baron",
        "lady",
        "viscount",
        "dame",
        "earl",
        "countess",
    ]
    if any(title in name_lower for title in lord_titles):
        return "lord"

    # Default to MP for now (might need manual verification)
    return "mp"


def update_appg_membership(
    appg_slug: str, member_names: list[str], update_date: Optional[date] = None
) -> bool:
    """
    Update an APPG's membership with the manual data.

    Args:
        appg_slug: APPG slug
        member_names: List of member names
        update_date: Date of the update (defaults to today)

    Returns:
        True if successful, False otherwise
    """
    if update_date is None:
        update_date = date.today()

    try:
        # Load existing APPG
        appg = APPG.load(appg_slug)

        # Check if we're working with AI search data (adaptive mode)
        if appg.members_list.source_method in ["ai_search", "ai_search_with_manual"]:
            # Adaptive mode: merge manual names with existing AI search data
            console.print(
                f"[blue]🔄 Merging manual data with existing AI search data for {appg_slug}[/blue]"
            )

            # Get existing member names (normalize for comparison)
            existing_names = {
                member.name.lower().strip() for member in appg.members_list.members
            }

            # Add new manual members that don't already exist
            new_members_added = 0
            for name in member_names:
                normalized_name = name.lower().strip()
                if normalized_name not in existing_names:
                    member_type = infer_member_type(name)
                    appg.members_list.members.append(
                        Member(
                            name=name.strip(),
                            is_officer=False,  # Can't determine from manual data
                            member_type=member_type,
                        )
                    )
                    new_members_added += 1

            # Update metadata to indicate manual data was merged
            appg.members_list.source_method = "ai_search_with_manual"
            appg.members_list.last_updated = update_date

            if new_members_added > 0:
                console.print(
                    f"[green]✓ Added {new_members_added} new manual members to existing AI search data for {appg_slug}[/green]"
                )
                appg.save()
                return True
            else:
                console.print(
                    f"[yellow]⚠ No new members to add for {appg_slug}: all manual names already present[/yellow]"
                )
                return False

        # Only update if current source is empty, manual, or not_found
        elif appg.members_list.source_method not in ["empty", "manual", "not_found"]:
            console.print(
                f"[yellow]⚠ Skipping {appg_slug}: already has {appg.members_list.source_method} data (use adaptive merge for ai_search)[/yellow]"
            )
            return False

        # Original behavior for empty/manual/not_found - complete replacement
        members = []
        for name in member_names:
            member_type = infer_member_type(name)
            members.append(
                Member(
                    name=name.strip(),
                    is_officer=False,  # Can't determine from manual data
                    member_type=member_type,
                )
            )

        # Update the APPG
        appg.members_list.source_method = "manual"
        appg.members_list.last_updated = update_date
        appg.members_list.members = members
        appg.members_list.source_url = []  # Clear any previous URLs

        # Save the updated APPG
        appg.save()

        console.print(
            f"[green]✓ Updated {appg_slug} with {len(members)} members[/green]"
        )
        return True

    except FileNotFoundError:
        console.print(f"[red]✗ APPG not found: {appg_slug}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Failed to update {appg_slug}: {e}[/red]")
        return False


def load_manual_data(
    skip_download: bool = False,
    markdown_file: Path = MARKDOWN_FILE,
    target_slug: str = "",
) -> bool:
    """
    Main function to load manual APPG membership data.

    Args:
        skip_download: If True, skip downloading and use existing file
        markdown_file: Path to markdown file to parse
        target_slug: If provided, only update this specific APPG slug

    Returns:
        True if successful, False otherwise
    """
    # Download markdown if needed
    if not skip_download:
        if not download_markdown(output_path=markdown_file):
            return False
    elif not markdown_file.exists():
        console.print(f"[red]✗ Markdown file not found: {markdown_file}[/red]")
        console.print(
            "[yellow]Run without --skip-download to download it first[/yellow]"
        )
        return False

    # Read and parse the markdown
    try:
        with markdown_file.open("r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        console.print(f"[red]✗ Failed to read markdown file: {e}[/red]")
        return False

    console.print(f"[blue]Parsing markdown file:[/blue] {markdown_file}")
    appg_data = parse_markdown_content(content)

    if not appg_data:
        console.print("[yellow]⚠ No APPG data found in markdown[/yellow]")
        return False

    console.print(f"[green]✓ Found {len(appg_data)} APPGs in markdown[/green]")

    # If target_slug is specified, show what we're filtering to
    if target_slug:
        console.print(f"[yellow]🎯 Filtering to target slug:[/yellow] {target_slug}")

    # Process each APPG
    updated_count = 0
    target_found = False
    for appg_title, member_names in appg_data.items():
        console.print(f"\n[blue]Processing:[/blue] {appg_title}")
        console.print(f"[blue]Members found:[/blue] {len(member_names)}")

        # Find matching APPG file
        appg_slug = find_matching_appg_file(appg_title)
        if not appg_slug:
            inferred_slug = appg_title_to_slug(appg_title)
            console.print(
                f"[red]✗ No matching APPG file found for '{appg_title}'[/red]"
            )
            console.print(f"[yellow]  Tried inferred slug: {inferred_slug}[/yellow]")
            continue

        console.print(f"[green]✓ Found matching file:[/green] {appg_slug}")

        # If target_slug is specified, check if this matches
        if target_slug and appg_slug != target_slug:
            console.print(f"[yellow]⏭ Skipping {appg_slug} (not target slug)[/yellow]")
            continue

        # If we have a target slug and found a match, mark it as found
        if target_slug and appg_slug == target_slug:
            target_found = True

        # Show first few member names for verification
        if member_names:
            sample_names = member_names[:3]
            console.print(f"[blue]Sample members:[/blue] {', '.join(sample_names)}")
            if len(member_names) > 3:
                console.print(f"[blue]... and {len(member_names) - 3} more[/blue]")

        # Update the APPG
        if update_appg_membership(appg_slug, member_names):
            updated_count += 1

    # Check if target slug was specified but not found
    if target_slug and not target_found:
        console.print(
            f"\n[red]✗ Target slug '{target_slug}' not found in markdown data[/red]"
        )
        console.print("[yellow]Available APPGs in markdown:[/yellow]")
        for title in appg_data.keys():
            slug = find_matching_appg_file(title)
            if slug:
                console.print(f"  - {slug} (from '{title}')")
        return False

    console.print(f"\n[green]✓ Successfully updated {updated_count} APPGs[/green]")
    return updated_count > 0


if __name__ == "__main__":
    load_manual_data()
