from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from appg_membership.models import APPGList, register_dates


class LineDiff(BaseModel):
    key: str
    old_value: str
    new_value: str


class MiniAppg(BaseModel):
    slug: str
    title: str
    source_url: str = ""

    @property
    def short_title(self):
        if not self.title:
            return self.slug
        s = self.title
        s = s.replace("All-Party Parliamentary Group for ", "")
        s = s.replace(" All-Party Parliamentary Group", "")
        s = s.replace("All-Party Parliamentary Group on ", "")
        # ensure first letter is capitalised
        s = s[0].upper() + s[1:]
        return s


class APPGDiff(BaseModel):
    slug: str
    name: str
    differences: list[LineDiff]
    source_url: str = ""  # URL to the source page in Parliament website


def get_appg_url(index_date: str, slug: str) -> str:
    return (
        f"https://publications.parliament.uk/pa/cm/cmallparty/{index_date}/{slug}.htm"
    )


class DiffResult(BaseModel):
    current_index: str
    previous_index: str
    added_appgs: list[MiniAppg]  # replaced list of slugs with list of MiniAppg objects
    removed_appgs: list[
        MiniAppg
    ]  # replaced list of slugs with list of MiniAppg objects
    updated_appgs: list[
        MiniAppg
    ]  # replaced list of slugs with list of MiniAppg objects
    differences: list[APPGDiff]

    def save(self):
        p = Path("data", "interim", "diffs")

        p.mkdir(parents=True, exist_ok=True)

        diff_file = p / f"{self.current_index}.json"

        with diff_file.open("w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    def generate_jekyll_pages(self):
        """
        Generate markdown files for the Jekyll site in the docs/_diffs/ directory.
        Creates a single consolidated page for each register date with all changes.
        """
        # Create _diffs directory if it doesn't exist
        diffs_dir = Path("docs", "_diffs")
        diffs_dir.mkdir(parents=True, exist_ok=True)

        # Create the consolidated diff page for this register date
        diff_filename = f"{self.current_index}.md"
        diff_path = diffs_dir / diff_filename

        with diff_path.open("w", encoding="utf-8") as f:
            # Write front matter
            f.write("---\n")
            f.write(f'title: "Changes in {self.current_index} Register"\n')
            f.write(f'previous_register: "{self.previous_index}"\n')
            f.write(f'current_register: "{self.current_index}"\n')
            f.write("layout: datasets/analysis\n")
            f.write("external_js:\n")
            f.write("  - //cdn.datatables.net/2.3.0/js/dataTables.min.js\n")
            f.write("external_css:\n")
            f.write(" - //cdn.datatables.net/2.3.0/css/dataTables.dataTables.min.css\n")
            f.write("---\n\n")

            # Write summary statistics
            f.write(
                f"# APPG Register Changes: {self.previous_index} → {self.current_index}\n\n"
            )

            # Table of contents with anchor links
            f.write("## Table of Contents\n\n")
            f.write("- [Summary](#summary)\n")
            if self.added_appgs:
                f.write("- [Added APPGs](#added-appgs)\n")
            if self.removed_appgs:
                f.write("- [Removed APPGs](#removed-appgs)\n")
            if self.updated_appgs:
                f.write("- [Updated APPGs](#updated-appgs)\n")
            f.write("\n")

            # Write summary section
            f.write("## Summary {#summary}\n\n")
            f.write(f"- **Added APPGs**: {len(self.added_appgs)}\n")
            f.write(f"- **Removed APPGs**: {len(self.removed_appgs)}\n")
            f.write(f"- **Updated APPGs**: {len(self.updated_appgs)}\n\n")

            # List added APPGs
            if self.added_appgs:
                f.write("## Added APPGs {#added-appgs}\n\n")
                for appg in sorted(self.added_appgs, key=lambda x: x.title):
                    # Use the source_url if available, otherwise generate one
                    parliament_url = appg.source_url or get_appg_url(
                        self.current_index, appg.slug
                    )
                    f.write(f"- [{appg.short_title}]({parliament_url})\n")
                f.write("\n")

            # List removed APPGs
            if self.removed_appgs:
                f.write("## Removed APPGs {#removed-appgs}\n\n")
                for appg in sorted(self.removed_appgs, key=lambda x: x.title):
                    # Use the source_url if available, otherwise generate one
                    parliament_url = appg.source_url or get_appg_url(
                        self.previous_index, appg.slug
                    )
                    f.write(f"- [{appg.short_title}]({parliament_url})\n")
                f.write("\n")

            # List all updated APPGs with details directly in this page
            if self.updated_appgs:
                f.write("## Updated APPGs {#updated-appgs}\n\n")

                # Create a section for each updated APPG
                for appg in sorted(self.updated_appgs, key=lambda x: x.short_title):
                    # Find the corresponding diff
                    diff = next(
                        (d for d in self.differences if d.slug == appg.slug), None
                    )
                    if not diff:
                        continue

                    # Create kebab-case anchor link
                    anchor = f"changes-to-{appg.slug.lower().replace('_', '-')}"

                    f.write(f"### Changes to {appg.short_title} {{#{anchor}}}\n\n")

                    # Add link to Parliament source URL
                    if diff.source_url:
                        f.write(f"[View on Parliament website]({diff.source_url})\n\n")
                    else:
                        # Use the source_url from the MiniAppg or generate one
                        parliament_url = appg.source_url or get_appg_url(
                            self.current_index, appg.slug
                        )
                        f.write(f"[View on Parliament website]({parliament_url})\n\n")

                    # Format each difference in a table
                    f.write("| Field | Previous Value | Current Value |\n")
                    f.write("|-------|---------------|---------------|\n")

                    for line_diff in diff.differences:
                        # Format the key for better readability
                        readable_key = line_diff.key.replace("__", " › ")

                        # Escape pipe characters in markdown table
                        old_value = line_diff.old_value.replace("|", "\\|")
                        new_value = line_diff.new_value.replace("|", "\\|")

                        f.write(f"| {readable_key} | {old_value} | {new_value} |\n")

                    f.write("\n")
                    # Add a return to top link at the end of each section
                    f.write("[Return to Table of Contents](#table-of-contents)\n\n")


def flatten(obj: dict | list, parent_key: str = "", sep: str = "__") -> dict:
    """
    Recursively flattens a JSON-like structure (dicts & lists).

    """
    out = {}

    # Handle dictionaries
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else str(key)
            out.update(flatten(value, new_key, sep))

    # Handle lists / tuples
    elif isinstance(obj, (list, tuple)):
        for idx, value in enumerate(obj):
            new_key = f"{parent_key}{sep}{idx}" if parent_key else str(idx)
            out.update(flatten(value, new_key, sep))

    # Handle scalars (leaf nodes)
    else:
        out[parent_key] = obj

    return out


def compare_registers(
    current_register_date: str, previous_register_date: Optional[str] = None
) -> DiffResult:
    """
    Compare APPGs between the current register and the previous one.

    Args:
        current_register_date: The date of the current register to compare
        previous_register_date: The date of the previous register to compare against.
            If None, will use the chronologically previous register.

    Returns:
        DiffResult containing the differences between the two registers
    """
    # Default keys to ignore if not specified
    ignore_keys = {"index_date", "category", "source_url"}

    # Get all register dates
    dates = register_dates

    # If previous_register_date is not specified, find the chronologically previous one
    if previous_register_date is None:
        try:
            current_index = dates.index(current_register_date)
            # If current register is not the oldest one, get the previous
            if current_index > 0:
                previous_register_date = dates[current_index - 1]
            else:
                # If it's the oldest, we have nothing to compare against
                raise ValueError(
                    f"Register date {current_register_date} is the oldest available, no previous register to compare with"
                )
        except ValueError:
            raise ValueError(
                f"Register date {current_register_date} not found in available registers"
            )

    # Load both registers
    current_register = APPGList.load(release=current_register_date)
    previous_register = APPGList.load(release=previous_register_date)

    # Create dictionaries with slug as key for easy lookup
    current_appgs = {appg.slug: appg for appg in current_register}
    previous_appgs = {appg.slug: appg for appg in previous_register}

    # Find added and removed APPGs
    added_appgs = [
        MiniAppg(slug=appg.slug, title=appg.title, source_url=str(appg.source_url))
        for appg in current_register
        if appg.slug not in previous_appgs
    ]
    removed_appgs = [
        MiniAppg(slug=appg.slug, title=appg.title, source_url=str(appg.source_url))
        for appg in previous_register
        if appg.slug not in current_appgs
    ]

    # Process differences for APPGs that exist in both registers
    differences = []
    updated_appgs = []

    for slug in set(current_appgs.keys()) & set(previous_appgs.keys()):
        current_appg = current_appgs[slug]
        previous_appg = previous_appgs[slug]

        # Convert to dict and flatten for easier comparison
        current_flat = flatten(current_appg.model_dump())
        previous_flat = flatten(previous_appg.model_dump())

        # Compare all keys, excluding the ones in ignore_keys
        appg_diffs = []
        for key in set(current_flat.keys()) | set(previous_flat.keys()):
            # Skip the ignored keys
            if any(ignored_key in key for ignored_key in ignore_keys):
                continue

            current_value = str(current_flat.get(key, ""))
            previous_value = str(previous_flat.get(key, ""))

            if current_value != previous_value:
                appg_diffs.append(
                    LineDiff(key=key, old_value=previous_value, new_value=current_value)
                )

        # If we found differences, add to our results
        if appg_diffs:
            updated_appgs.append(
                MiniAppg(
                    slug=slug,
                    title=current_appg.title,
                    source_url=str(current_appg.source_url),
                )
            )
            # Get the source_url from the current APPG
            source_url = (
                current_appg.source_url if hasattr(current_appg, "source_url") else ""
            )

            differences.append(
                APPGDiff(
                    slug=slug,
                    name=current_appg.title,
                    differences=appg_diffs,
                    source_url=str(source_url),
                )
            )

    # Create and return the final diff result
    return DiffResult(
        current_index=current_register_date,
        previous_index=previous_register_date,
        added_appgs=added_appgs,
        removed_appgs=removed_appgs,
        updated_appgs=updated_appgs,
        differences=differences,
    )


def compare_all_registers():
    for register_date in register_dates[1:]:
        print(f"Comparing APPGs between {register_date} and the previous register")
        diff_result = compare_registers(register_date)
        diff_result.save()
        # Generate Jekyll pages for the diffs
        diff_result.generate_jekyll_pages()


def generate_all_jekyll_diff_pages():
    """
    Generate Jekyll markdown pages for all existing diff files.
    This can be used to regenerate the Jekyll pages without recomputing the diffs.
    """
    diffs_dir = Path("data", "interim", "diffs")

    if not diffs_dir.exists():
        print(f"No diffs directory found at {diffs_dir}")
        return

    for diff_file in diffs_dir.glob("*.json"):
        print(f"Generating Jekyll pages for {diff_file.stem}")
        with diff_file.open("r", encoding="utf-8") as f:
            diff_result = DiffResult.model_validate_json(f.read())
            diff_result.generate_jekyll_pages()


def generate_diffs():
    compare_all_registers()
    generate_all_jekyll_diff_pages()


if __name__ == "__main__":
    compare_all_registers()
    generate_all_jekyll_diff_pages()
