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

    # Remove leading/trailing whitespace
    line = line.strip()

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
    # Remove common prefixes
    title_clean = title
    prefixes_to_remove = [
        "All-Party Parliamentary Group for",
        "All-Party Parliamentary Group on",
        "All-Party Parliamentary Group",
        "APPG for",
        "APPG on",
        "APPG",
    ]

    for prefix in prefixes_to_remove:
        if title_clean.startswith(prefix):
            title_clean = title_clean[len(prefix) :].strip()
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
                "appg for",
                "appg on",
                "appg",
            ]:
                if existing_title.startswith(prefix):
                    existing_title = existing_title[len(prefix) :].strip()
                if markdown_title.startswith(prefix):
                    markdown_title = markdown_title[len(prefix) :].strip()

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

        # Only update if current source is empty or manual
        if appg.members_list.source_method not in ["empty", "manual"]:
            console.print(
                f"[yellow]⚠ Skipping {appg_slug}: already has {appg.members_list.source_method} data[/yellow]"
            )
            return False

        # Create new member list
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
    skip_download: bool = False, markdown_file: Path = MARKDOWN_FILE
) -> bool:
    """
    Main function to load manual APPG membership data.

    Args:
        skip_download: If True, skip downloading and use existing file
        markdown_file: Path to markdown file to parse

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

    # Process each APPG
    updated_count = 0
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

        # Show first few member names for verification
        if member_names:
            sample_names = member_names[:3]
            console.print(f"[blue]Sample members:[/blue] {', '.join(sample_names)}")
            if len(member_names) > 3:
                console.print(f"[blue]... and {len(member_names) - 3} more[/blue]")

        # Update the APPG
        if update_appg_membership(appg_slug, member_names):
            updated_count += 1

    console.print(f"\n[green]✓ Successfully updated {updated_count} APPGs[/green]")
    return updated_count > 0


if __name__ == "__main__":
    load_manual_data()
