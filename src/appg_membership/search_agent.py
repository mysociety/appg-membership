import httpx
from pydantic import BaseModel, Field
from pydantic.networks import HttpUrl
from pydantic_ai import Agent
from pydantic_ai.common_tools.tavily import tavily_search_tool
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from tqdm import tqdm

from appg_membership.config import settings
from appg_membership.models import APPG, APPGList

model = OpenAIModel("gpt-4o", provider=OpenAIProvider(api_key=settings.OPENAI_APIKEY))


class APPGSearchOutput(BaseModel):
    has_website: bool = Field(..., description="Whether the APPG has a website or not")
    url: str | None = Field(
        ..., description="The URL of the APPG page if it exists, otherwise None"
    )
    desc: str = Field(
        ..., description="A description of the APPG page if it exists, otherwise None"
    )


def check_if_url_404(url: str) -> bool:
    """
    Check if the given URL gives a 404 code.
    """
    try:
        response = httpx.get(url)
        return response.status_code == 404
    except httpx.RequestError as e:
        print(f"Error checking URL {url}: {e}")
        return True


prompt = """
You are searching for the page on the internet of a given all party parliamentary group (APPG) in the UK Parliament.
You will be given the name of the APPG and you should search for the page on the UK Parliament website.
This is not the site in the register on parliament.uk or parallelparliament.co.uk - but will be a seperate page, sometimes hosted
by the convening organisation of the APPG (so might sit as subpages on a seperate site.)

Sometimes the APPG will not have a page, in which case you should say so rather than using unlikely candidates. 

Sometimes you will find a blog post or a news article about the APPG, but not the page itself. This is not what we're looking for.

You might need to try several variations of the name of the APPG to find the page.
for instance '[x] APPG' or 'All-Party Parliamentary Group on [x]'

Sometimes an APPG's website used to exist but doesn't - worth checking the final candidate for a 404 error.

"""

# Create a new agent instance with the provided message and output type
agent = Agent(
    model,
    system_prompt=prompt,
    tools=[tavily_search_tool(api_key=settings.TAVITY_API_KEY), check_if_url_404],
    output_type=APPGSearchOutput,
)


def search_for_appg(appg: APPG) -> APPGSearchOutput:
    """
    Search for the APPG page on the internet using the provided name.
    """
    # Create a message with the APPG name
    message = f"Search for the page of the {appg.title}"

    # Run the agent with the message and return the output
    return agent.run_sync(message).output


def update_website(override: bool = False, slug: str = ""):
    override_values = ["no_register"]
    if override:
        override_values.append("search")
        override_values.append("no_search")
    appgs = APPGList.load()
    # appgs.root = appgs.root[:5]

    if slug:
        appgs = [x for x in appgs if x.slug == slug]

    for appg in tqdm(appgs):
        if appg.contact_details.website.status in override_values:
            tqdm.write(f"Searching for {appg.title}...")
            search = search_for_appg(appg)
            if search.has_website and search.url:
                appg.contact_details.website.status = "search"
                appg.contact_details.website.url = HttpUrl(search.url)
                tqdm.write(
                    f"Found website for {appg.title}: {search.url} ({search.desc})"
                )
            if not search.has_website:
                appg.contact_details.website.status = "no_search"
                tqdm.write(f"No website found for {appg.title}")
            appg.save()


if __name__ == "__main__":
    update_website(slug="heritage-rail")
