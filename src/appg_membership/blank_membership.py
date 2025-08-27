from appg_membership.models import APPGList


def blank_membership_information(appg_slug: str) -> bool:
    """
    Blank the membership information for a given APPG slug.

    This function:
    1. Marks the search method as 'empty'
    2. Removes all members from the members list
    3. Saves the updated data

    Args:
        appg_slug: The slug of the APPG to blank membership information for

    Returns:
        bool: True if the APPG was found and updated, False if not found
    """
    appg_list = APPGList.load()

    # Find the APPG by slug
    target_appg = None
    for appg in appg_list:
        if appg.slug == appg_slug:
            target_appg = appg
            break

    if target_appg is None:
        print(f"Error: APPG with slug '{appg_slug}' not found")
        return False

    # Store original member count for reporting
    original_member_count = len(target_appg.members_list.members)

    # Mark search as empty and clear members
    target_appg.members_list.source_method = "empty"
    target_appg.members_list.members = []
    target_appg.members_list.source_url = []
    target_appg.members_list.last_updated = None

    # Save the updated APPG
    target_appg.save()

    print(f"Successfully blanked membership information for '{appg_slug}':")
    print("  - Set source method to 'empty'")
    print(f"  - Removed {original_member_count} members")
    print("  - Cleared source URLs")

    return True
