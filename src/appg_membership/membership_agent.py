from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from pydantic.networks import HttpUrl
from pydantic_ai import Agent, ModelHTTPError
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from tqdm import tqdm

from appg_membership.agent_functions import get_url_as_markdown
from appg_membership.config import settings
from appg_membership.models import APPG, APPGList, Member

model = OpenAIModel("gpt-4o", provider=OpenAIProvider(api_key=settings.OPENAI_APIKEY))


def remove_all_whitespace(text: str) -> str:
    """
    Remove all whitespace inc newlines and tabs from the text.
    """
    return "".join(text.split())


class APPGMember(BaseModel):
    name: str = Field(..., description="The name of the APPG member")
    is_officer: bool = Field(..., description="If the member is an officer of the APPG")
    type: Literal["mp", "lord", "other"] = Field(
        ..., description="The type of the member (MP, Lord, or other)"
    )
    officer_role: str = Field(..., description="The role of the officer in the APPG")


class APPGSourcePage(BaseModel):
    source_url: str = Field(
        ...,
        description="The URL of the APPG page that contains the membership list that was sourced, empty if there is none",
    )
    members: list[APPGMember] = Field(default_factory=list)

    def check_names_present(self) -> bool:
        """
        Fetch the stated source page and
        check if the names of the members are present in the page.
        """
        # Fetch the source page
        md_content = get_url_as_markdown(self.source_url)
        try:
            md_content = remove_all_whitespace(md_content.lower())
        except Exception as e:
            print(f"Error decoding content from {self.source_url}: {e}")
            return False

        # Check if all member names are present in the content
        for member in self.members:
            if remove_all_whitespace(member.name.lower()) not in md_content:
                print(f"Member {member.name} not found in {self.source_url}.")
                return False
        return True


class APPGMemberList(BaseModel):
    members_list_found: bool = Field(
        ..., description="Whether the APPG has a list of members"
    )
    source_pages: list[APPGSourcePage] = Field(
        default_factory=list,
        description="The source page(s) that contain the membership list",
    )

    def single_url_string(self) -> str:
        return ", ".join(str(x.source_url) for x in self.source_pages)

    def source_urls(self) -> list[HttpUrl]:
        """
        Get the source URL of the first source page.
        """
        if self.source_pages:
            return [HttpUrl(x.source_url) for x in self.source_pages]
        return []

    def all_members(self) -> list[APPGMember]:
        """
        Get all members from the source pages.
        """
        all_members = []
        for source_page in self.source_pages:
            all_members.extend(source_page.members)
        return all_members

    def check_names_present(self) -> bool:
        """
        Check if the names of the members are present in the source page.
        """
        if not self.members_list_found:
            return False

        # Check if all member names are present in the content
        for source_page in self.source_pages:
            if not source_page.check_names_present():
                return False
        return True


prompt = """
You are navigating around a website looking for a list of members of an All-Party Parliamentary Group (APPG).
APPGs are required to publish a list of their members on their website.
However, some don't - so not finding it is not a failure and should be reported as such.
You will be given a name of an APPG and a URL to search.

Starting at this URL, the first thing to do is to see if there is a link to a page that contains a list of members.
This might be called APPG members, membership, officers, etc.
If there is a good candidate for this - fetch this link and review the contents. If not, review the content of the starting page.

Look for clues you are looking at a partial list and need to hunt for the full one - e.g. attendees at a meeting, or a list of officers is not a full list of members.

Sometimes this is spread over *multiple* pages, e.g. a page for MPs, a page for Lords, and a page for other members (associate members or similar). You'll need to get each of these.
Associate members are likely to be organisations rather than people. 

If you are on a page that might contain the membership list, examine the page looking for a list of members that goes beyond the officers. 
You need to determine if there is a list of members, and if so, return the list of members.
Remove the honourific 'MP' but keep Lords titles.
If there is no list of members, return an empty list.
"""

# Create a new agent instance with the provided message and output type
agent = Agent(
    model,
    system_prompt=prompt,
    tools=[get_url_as_markdown],
    output_type=APPGMemberList,
)


def search_for_appg_members(appg: APPG, recursion: int = 0) -> APPGMemberList:
    """
    Search for the APPG page on the internet using the provided name.
    """
    # Create a message with the APPG name
    message = f"Search for the members of the {appg.title} starting at {appg.contact_details.website.url}"

    # Run the agent with the message and return the output
    try:
        results = agent.run_sync(message).output
    except ModelHTTPError as e:
        print(f"Error fetching the page: {appg.contact_details.website.url}")
        print(f"Error: {e}")
        return APPGMemberList(members_list_found=False, source_pages=[])

    if results.source_pages:
        # Check if the members are present in the source URL
        if results.check_names_present():
            return results
        else:
            # If not found, try to search again with a different URL
            if recursion < 3:
                recursion += 1
                return search_for_appg_members(appg, recursion=recursion)
            else:
                return APPGMemberList(members_list_found=False, source_pages=[])
    else:
        return results


def update_appgs_membership(override: bool = False, slug: str = ""):
    appgs = APPGList.load()
    appgs = [x for x in appgs if x.has_website()]

    # appgs = [x for x in appgs if x.slug=="cycling-and-walking"]

    epoch_date = date(2025, 4, 28)

    if slug:
        appgs = [x for x in appgs if x.slug == slug]
    else:
        if not override:
            appgs = [
                x
                for x in appgs
                if not x.members_list.last_updated
                or (x.members_list.last_updated < epoch_date)
            ]

    for appg in tqdm(appgs):
        tqdm.write(f"Searching for {appg.title}...")
        search = search_for_appg_members(appg)

        if not search.members_list_found:
            if appg.members_list.source_method in ["empty", "ai_search"]:
                appg.members_list.source_method = "empty"
                appg.members_list.last_updated = date.today()
                appg.members_list.source_url = []
                appg.members_list.members = []
                appg.save()

        if search.members_list_found and search.source_pages:
            tqdm.write(
                f"Found members list for {appg.title}: {search.single_url_string()} ({len(search.all_members())} members)"
            )
            appg.members_list.source_method = "ai_search"
            appg.members_list.last_updated = date.today()
            appg.members_list.source_url = search.source_urls()

            # Get all new members from the search
            new_members_names = [member.name for member in search.all_members()]
            added_count = 0
            removed_count = 0

            # Mark existing members as removed if they're not in the new list
            for existing_member in appg.members_list.members:
                if existing_member.name not in new_members_names:
                    if not existing_member.removed:
                        existing_member.removed = True
                        removed_count += 1
                else:
                    # If the member was previously marked as removed but is now present, unmark them
                    if existing_member.removed:
                        existing_member.removed = False

            # Add new members that aren't already in the list
            for new_member in search.all_members():
                if new_member.name not in [x.name for x in appg.members_list.members]:
                    appg.members_list.members.append(
                        Member(
                            name=new_member.name,
                            is_officer=new_member.is_officer,
                            member_type=new_member.type,
                        )
                    )
                    added_count += 1

            if added_count > 0 or removed_count > 0:
                tqdm.write(
                    f"Added {added_count} new members and marked {removed_count} members as removed for {appg.title} ({len(appg.members_list.members)} total)"
                )
            appg.save()


if __name__ == "__main__":
    update_appgs_membership()
