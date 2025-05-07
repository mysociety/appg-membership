import json

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from appg_membership.config import settings
from appg_membership.models import APPG, AppgCategory

model = OpenAIModel("gpt-4o", provider=OpenAIProvider(api_key=settings.OPENAI_APIKEY))


prompt = """
You are classifying a Parliamentary APPG into one or more categories (ideally one, but multiple if they fit).

You will be given the title and purpose of the group - and classify it based on the schema provided
"""

# Create a new agent instance with the provided message and output type


def classify_appg(appg: APPG) -> APPG:
    agent = Agent(
        model,
        system_prompt=prompt,
        output_type=list[AppgCategory],
    )

    message = json.dumps({"title": appg.title, "purpose": appg.purpose})

    results = agent.run_sync(message).output

    appg.categories = results

    return appg
