import heapq
from datetime import date

import Levenshtein
from mysoc_validator import Popolo
from mysoc_validator.models.consts import Chamber
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from appg_membership.models import NameCorrectionList


def get_bad_names():
    """
    Get a list of bad names from the NameCorrectionList.
    """
    bad_names = [x for x in NameCorrectionList.load() if not x.canon]

    pop = Popolo.from_parlparse()

    current_posts = [x.id for x in pop.posts if x.organization_id == Chamber.COMMONS]

    print(f"Found {len(current_posts)} current posts")
    current_mps = [
        x.person()
        for x in pop.memberships
        if (x.end_date > date.today()) and (x.post_id in current_posts)
    ]
    names = []
    for mp in current_mps:
        if mp:
            for name in mp.names:
                names.append(name.nice_name())

    print(f"Found {len(current_mps)} current MPs")

    return bad_names, names


def calculate_string_distances(name, current_mps, threshold=0.7):
    """
    Calculate string distances between a name and a list of MP names.
    Returns a list of (distance, mp_name) tuples, sorted by distance.
    Lower distance means better match.
    """
    distances = []
    for mp_name in current_mps:
        # Calculate normalized Levenshtein distance
        distance = Levenshtein.distance(name.lower(), mp_name.lower())
        max_len = max(len(name), len(mp_name))
        normalized_distance = distance / max_len if max_len > 0 else 1.0

        # Lower score is better
        if normalized_distance <= threshold:
            distances.append((normalized_distance, mp_name))

    # Return sorted by distance (best matches first)
    return sorted(distances)


def correct_names(threshold=0.5, max_suggestions=5):
    """
    Interactive terminal app to correct misspelled MP names.
    """
    console = Console()

    try:
        bad_names, current_mps = get_bad_names()
    except FileNotFoundError:
        # Create an empty corrections list if it doesn't exist
        corrections = NameCorrectionList(root=[])
        corrections.save()
        bad_names, current_mps = [], []
        console.print("[yellow]Created new empty name corrections file[/yellow]")

    if not bad_names:
        console.print("[green]No bad names to correct![/green]")
        return

    corrections = NameCorrectionList.load()
    corrected_count = 0

    console.print(f"[bold]Found {len(bad_names)} names to correct[/bold]")
    console.print(f"Using threshold {threshold} (lower means stricter matching)")

    for bad_name in bad_names:
        original_name = bad_name.original
        console.print(
            f"\n[bold yellow]Correcting:[/bold yellow] [bold]{original_name}[/bold]"
        )

        # Calculate distances to all current MPs
        distances = calculate_string_distances(
            original_name, current_mps, threshold=1.0
        )  # Allow high threshold for calculation

        # Filter by user-specified threshold and limit suggestions
        filtered_distances = [(d, name) for d, name in distances if d <= threshold]
        top_suggestions = heapq.nsmallest(max_suggestions, filtered_distances)

        if not top_suggestions:
            console.print("[red]No matches found within threshold[/red]")
            action = Prompt.ask(
                "Options",
                choices=["s", "m", "i", "k", "q"],
                default="s",
                show_choices=True,
                show_default=True,
            )
        else:
            # Show suggestions in a table
            table = Table(show_header=True, header_style="bold")
            table.add_column("#", style="dim", width=3)
            table.add_column("Distance", width=10)
            table.add_column("MP Name")

            for i, (distance, mp_name) in enumerate(top_suggestions, 1):
                table.add_row(str(i), f"{distance:.3f}", mp_name)

            console.print(table)

            # Ask for selection or other options
            options = [str(i) for i in range(1, len(top_suggestions) + 1)] + [
                "s",
                "m",
                "i",
                "k",
                "q",
            ]
            action = Prompt.ask(
                "Select an option (number to choose, s to skip, m for manual entry, i to ignore, k to keep as is, q to quit)",
                choices=options,
                default="s",
            )

        # Process the selected action
        if action.isdigit() and 1 <= int(action) <= len(top_suggestions):
            selected_idx = int(action) - 1
            selected_mp = top_suggestions[selected_idx][1]

            # Update the correction in the list
            for item in corrections.root:
                if item.original == original_name:
                    item.canon = selected_mp
                    break

            console.print(f"[green]Corrected to: {selected_mp}[/green]")
            corrected_count += 1

        elif action == "m":
            # Manual entry
            manual_name = Prompt.ask("Enter correct name manually")

            # Update the correction in the list
            for item in corrections.root:
                if item.original == original_name:
                    item.canon = manual_name
                    break

            console.print(f"[green]Manually set to: {manual_name}[/green]")
            corrected_count += 1

        elif action == "i":
            # Ignore (don't change, but mark as processed by setting canon to IGNORE)
            for item in corrections.root:
                if item.original == original_name:
                    item.canon = "IGNORE"
                    break

            console.print("[yellow]Ignored[/yellow]")

        elif action == "k":
            # Keep as is (use the original name as canon)
            for item in corrections.root:
                if item.original == original_name:
                    item.canon = original_name
                    break

            console.print(
                f"[yellow]Keeping original name as canonical: {original_name}[/yellow]"
            )
            corrected_count += 1

        elif action == "q":
            # Quit the program
            break

        else:  # Skip
            console.print("[yellow]Skipped[/yellow]")

        # Save after each correction
        corrections.save()

    console.print(
        f"\n[bold green]Completed! Corrected {corrected_count} names.[/bold green]"
    )


if __name__ == "__main__":
    correct_names()
