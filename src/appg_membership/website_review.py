import webbrowser

from pydantic.networks import HttpUrl
from rich.console import Console
from rich.prompt import Prompt

from .models import APPGList

console = Console()


def review_website_candidates():
    """
    Interactive terminal app to review potential APPG websites found by automatic search.

    Goes through all APPGs with status 'search_precheck' and allows the user to:
    1. Accept the URL (changes status to 'search')
    2. Reject the URL (sets URL to None and status to 'bad_search')
    3. Provide a manual URL (sets the URL and status to 'manual')
    4. Skip (keep as 'search_precheck')
    """
    appgs = APPGList.load()

    # Filter for APPGs with search_precheck status
    precheck_appgs = [
        appg
        for appg in appgs
        if appg.contact_details.website.status == "search_precheck"
        and appg.contact_details.website.url is not None
    ]

    if not precheck_appgs:
        console.print("[yellow]No APPGs with 'search_precheck' status found.[/yellow]")
        return

    console.print(
        f"[green]Found {len(precheck_appgs)} APPGs with 'search_precheck' status to review.[/green]"
    )

    reviewed_count = 0
    accepted_count = 0
    rejected_count = 0
    manual_count = 0

    # Display help information at the beginning
    console.print("\n[bold cyan]== Website Review Options ==\n")
    console.print(
        "[bold white]a[/bold white] - [green]Accept[/green] the URL as valid (status → 'search')"
    )
    console.print(
        "[bold white]r[/bold white] - [red]Reject[/red] the URL as invalid (URL cleared, status → 'bad_search')"
    )
    console.print(
        "[bold white]m[/bold white] - [blue]Manual[/blue] entry of a different URL (status → 'manual')"
    )
    console.print(
        "[bold white]s[/bold white] - [yellow]Skip[/yellow] this APPG for now (status remains 'search_precheck')"
    )
    console.print(
        "[bold white]q[/bold white] - [magenta]Quit[/magenta] the review process and save progress"
    )
    console.print("")

    for appg in precheck_appgs:
        console.print("\n" + "=" * 80)
        console.print(f"[bold blue]APPG: {appg.title}[/bold blue]")
        console.print(f"[cyan]Suggested URL: {appg.contact_details.website.url}[/cyan]")

        # Option to open the URL in a browser
        open_url = Prompt.ask(
            "Open URL in browser to check?", choices=["y", "n"], default="y"
        )

        if open_url.lower() == "y":
            webbrowser.open(str(appg.contact_details.website.url))

        # Ask for decision with detailed option descriptions
        console.print("\n[bold]Available actions:[/bold]")
        console.print(
            "  [bold white]a[/bold white] - [green]Accept[/green]: Confirm this URL is valid (status → 'search')"
        )
        console.print(
            "  [bold white]r[/bold white] - [red]Reject[/red]: URL is not valid for this APPG (status → 'bad_search')"
        )
        console.print(
            "  [bold white]m[/bold white] - [blue]Manual[/blue]: Enter a different URL for this APPG (status → 'manual')"
        )
        console.print(
            "  [bold white]s[/bold white] - [yellow]Skip[/yellow]: Review this APPG later (status remains 'search_precheck')"
        )
        console.print(
            "  [bold white]q[/bold white] - [magenta]Quit[/magenta]: Exit review process and save progress"
        )

        action = Prompt.ask(
            "What would you like to do?", choices=["a", "r", "m", "s", "q"], default="s"
        )

        if action == "a":
            # Accept
            appg.contact_details.website.status = "search"
            console.print("[green]URL accepted as valid.[/green]")
            accepted_count += 1
            reviewed_count += 1

        elif action == "r":
            # Reject
            appg.contact_details.website.status = "bad_search"
            appg.contact_details.website.url = None
            console.print("[red]URL rejected.[/red]")
            rejected_count += 1
            reviewed_count += 1

        elif action == "m":
            # Manual entry
            manual_url = Prompt.ask("Enter correct URL manually")
            try:
                appg.contact_details.website.url = HttpUrl(manual_url)
                appg.contact_details.website.status = "manual"
                console.print(f"[green]Manually set URL to: {manual_url}[/green]")
                manual_count += 1
                reviewed_count += 1
            except Exception as e:
                console.print(f"[red]Invalid URL: {e}[/red]")
                console.print("[yellow]Skipping this APPG.[/yellow]")

        elif action == "q":
            # Quit
            console.print("[yellow]Quitting review process.[/yellow]")
            break

        else:
            # Skip
            console.print(
                "[yellow]Skipped. Will remain with 'search_precheck' status.[/yellow]"
            )

        # Save the updated APPG
        appg.save()

    # Print summary
    console.print("\n" + "=" * 80)
    console.print("[bold green]Review complete![/bold green]")
    console.print(
        f"Reviewed {reviewed_count} out of {len(precheck_appgs)} APPGs with 'search_precheck' status."
    )
    console.print(f"- Accepted: {accepted_count}")
    console.print(f"- Rejected: {rejected_count}")
    console.print(f"- Manual: {manual_count}")
    console.print(f"- Skipped: {len(precheck_appgs) - reviewed_count}")

    # Show remaining APPGs to review next time
    remaining = len(precheck_appgs) - reviewed_count
    if remaining > 0:
        console.print(
            f"\n[yellow]There are still {remaining} APPGs with 'search_precheck' status to review.[/yellow]"
        )
        console.print("[yellow]Run this command again to continue reviewing.[/yellow]")
