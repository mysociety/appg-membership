from datetime import date

from mysoc_validator import Popolo
from mysoc_validator.models.popolo import Chamber
from rich.console import Console
from rich.table import Table

from appg_membership.models import APPGList


class MembershipChecker:
    def __init__(self):
        self.popolo = Popolo.from_parlparse()
        self.today = date.today()

    def is_member_still_mp(self, twfy_id: str) -> bool:
        allowed_chambers = [Chamber.COMMONS, Chamber.LORDS]

        person = self.popolo.persons[twfy_id]

        memberships = person.memberships()
        if memberships:
            for m in memberships:
                post = m.post()
                if (post and post.organization_id in allowed_chambers) or (
                    not post and m.organization_id in allowed_chambers
                ):
                    if m.start_date <= self.today <= m.end_date:
                        return True
        return False


def find_appgs_with_old_members(format_type="list"):
    """
    Find APPGs that have members who are no longer MPs.

    Args:
        format_type: Either "list" for individual messages or "table" for summary table

    Prints either individual messages for each person who is listed as a member
    of an APPG but is no longer in Parliament, or a summary table.
    """
    appg_list = APPGList.load()

    checker = MembershipChecker()

    if format_type == "list":
        found_old_members = False

        for appg in appg_list:
            # Check officers
            for officer in appg.officers:
                if officer.twfy_id:  # Only check if we have a TWFY ID
                    if not checker.is_member_still_mp(officer.twfy_id):
                        print(
                            f"{officer.name} is listed as a member of {appg.slug} but is no longer in Parliament"
                        )
                        found_old_members = True

            # Check members list
            for member in appg.members_list.members:
                if member.twfy_id:  # Only check if we have a TWFY ID
                    if not checker.is_member_still_mp(member.twfy_id):
                        print(
                            f"{member.name} is listed as a member of {appg.slug} but is no longer in Parliament"
                        )
                        found_old_members = True

        if not found_old_members:
            print("No APPGs found with members who are no longer MPs.")

    elif format_type == "table":
        results = []

        for appg in appg_list:
            old_members_count = 0
            total_members_count = 0

            # Check officers
            for officer in appg.officers:
                if officer.twfy_id:  # Only check if we have a TWFY ID
                    total_members_count += 1
                    if not checker.is_member_still_mp(officer.twfy_id):
                        old_members_count += 1

            # Check members list
            for member in appg.members_list.members:
                if member.twfy_id:  # Only check if we have a TWFY ID
                    total_members_count += 1
                    if not checker.is_member_still_mp(member.twfy_id):
                        old_members_count += 1

            # Only include APPGs that have old members
            if old_members_count > 0 and total_members_count > 0:
                proportion = old_members_count / total_members_count
                significant = proportion >= 1 / 3  # True if 1/3 or more are old members
                results.append(
                    {
                        "name": appg.slug,
                        "old_members": old_members_count,
                        "total_members": total_members_count,
                        "proportion": proportion,
                        "significant": significant,
                    }
                )

        # Sort by proportion (highest first)
        results.sort(key=lambda x: x["proportion"], reverse=True)

        # Print results
        if results:
            console = Console()

            table = Table(
                title=f"Found {len(results)} APPGs with members who are no longer MPs"
            )
            table.add_column("APPG Slug", style="cyan", no_wrap=False, width=50)
            table.add_column("Old Members", justify="right", style="red")
            table.add_column("Total", justify="right", style="blue")
            table.add_column("Proportion", justify="right", style="magenta")
            table.add_column("Significant", justify="center", style="yellow")

            for result in results:
                proportion_pct = result["proportion"] * 100
                significant_text = "✓" if result["significant"] else ""
                table.add_row(
                    result["name"],
                    str(result["old_members"]),
                    str(result["total_members"]),
                    f"{proportion_pct:.1f}%",
                    significant_text,
                )

            console.print(table)
        else:
            print("No APPGs found with members who are no longer MPs.")


if __name__ == "__main__":
    find_appgs_with_old_members()
