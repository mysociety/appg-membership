from __future__ import annotations

from datetime import date
from json import dumps
from pathlib import Path
from typing import List, Literal, Optional

from backports.strenum import StrEnum
from pydantic import BaseModel, EmailStr, Field, HttpUrl, RootModel, field_validator


class Parliament(StrEnum):
    UK = "uk"
    SCOTLAND = "scotland"
    SENEDD_EN = "senedd-en"
    SENEDD_CY = "senedd-cy"
    NI = "ni"


register_dates = [
    "240828",  # 28 August 2024
    "241009",  # 9 October 2024
    "241120",  # 20 November 2024
    "250102",  # 2 January 2025
    "250212",  # 12 February 2025
    "250328",  # 28 March 2025
    "250507",  # 7 May 2025
    "250618",  # 18 June 2025
    "250731",  # 31 July 2025
    "250909",  # 9 September 2025
    "251201",  # 1 December 2025
    "260112",  # 12 January 2026
]

# MPs who are ineligible to be part of any APPG and should be marked as removed=True
ineligible_person_ids = {
    "uk.org.publicwhip/person/26384",
    # Add more ineligible person IDs here as they are identified
}


class AppgCategory(StrEnum):
    HEALTH_MEDICINE_PUBLIC_HEALTH = "Health, Medicine & Public Health"
    SOCIAL_CARE_WELFARE_FAMILY_SUPPORT = "Social Care, Welfare & Family Support"
    EDUCATION_SKILLS_YOUTH = "Education, Skills & Youth"
    SCIENCE_TECHNOLOGY_INNOVATION = "Science, Technology & Innovation"
    ENVIRONMENT_CLIMATE_SUSTAINABILITY = "Environment, Climate & Sustainability"
    ENERGY_UTILITIES = "Energy & Utilities"
    INFRASTRUCTURE_TRANSPORT_MOBILITY = "Infrastructure, Transport & Mobility"
    ECONOMY_BUSINESS_INDUSTRY = "Economy, Business & Industry"
    FINANCE_MARKETS_CONSUMER_AFFAIRS = "Finance, Markets & Consumer Affairs"
    FOOD_AGRICULTURE_RURAL_AFFAIRS = "Food, Agriculture & Rural Affairs"
    ANIMALS_ANIMAL_WELFARE = "Animals & Animal Welfare"
    ARTS_CULTURE_HERITAGE_MEDIA = "Arts, Culture, Heritage & Media"
    SPORT_RECREATION_PHYSICAL_ACTIVITY = "Sport, Recreation & Physical Activity"
    JUSTICE_LAW_SECURITY = "Justice, Law & Security"
    HUMAN_RIGHTS_EQUALITY_SOCIAL_JUSTICE = "Human Rights, Equality & Social Justice"
    INTERNATIONAL_AFFAIRS_DEVELOPMENT_TRADE = (
        "International Affairs, Development & Trade"
    )
    REGIONS_NATIONS_DEVOLUTION = "Regions, Nations & Devolution"
    HOUSING_PLANNING_BUILT_ENVIRONMENT = "Housing, Planning & Built Environment"
    GOVERNANCE_DEMOCRACY_POLITICAL_REFORM = "Governance, Democracy & Political Reform"
    RELIGION_FAITH_BELIEF_COMMUNITIES = "Religion, Faith & Belief Communities"
    OTHER = "Other"
    COUNTRY_GROUP = "Country Group"


class Member(BaseModel):
    name: str
    is_officer: bool = False
    member_type: Literal["mp", "lord", "msp", "ms", "mla", "other"]
    mnis_id: Optional[str] = None
    twfy_id: Optional[str] = None
    removed: bool = False


class MemberList(BaseModel):
    source_method: Literal[
        "official", "ai_search", "manual", "empty", "not_found", "ai_search_with_manual"
    ] = "empty"
    source_url: list[HttpUrl] = Field(default_factory=list)
    last_updated: Optional[date] = None
    members: List[Member] = Field(default_factory=list)

    @field_validator("source_url", mode="before")
    def _check_source_url(cls, v: HttpUrl | list[HttpUrl] | None) -> list[HttpUrl]:
        """
        Check if the source URL is a list of URLs.
        Backward compatibility for the old format.
        """
        if isinstance(v, str):
            return [HttpUrl(v)]
        elif isinstance(v, list):
            return [HttpUrl(url) for url in v]
        else:
            return []


class Officer(BaseModel):
    role: str
    name: str
    party: str
    twfy_id: Optional[str] = None
    mnis_id: Optional[str] = None
    removed: bool = False


class WebsiteSource(BaseModel):
    status: Literal[
        "register",
        "no_register",
        "search_precheck",
        "search",
        "no_search",
        "bad_search",
        "manual",
    ] = "no_register"
    url: Optional[HttpUrl] = None


class ContactDetails(BaseModel):
    registered_contact_name: Optional[str] = None
    registered_contact_address: Optional[str] = None
    registered_contact_email: Optional[EmailStr] = None

    public_enquiry_point_name: Optional[str] = None
    public_enquiry_point_email: Optional[EmailStr] = None

    secretariat: Optional[str] = None
    website: WebsiteSource

    def flattened_dict(self) -> dict[str, str]:
        """
        Flatten the contact details into a dictionary.
        """
        return {
            "registered_contact_name": self.registered_contact_name or "",
            "registered_contact_address": self.registered_contact_address or "",
            "registered_contact_email": self.registered_contact_email or "",
            "public_enquiry_point_name": self.public_enquiry_point_name or "",
            "public_enquiry_point_email": self.public_enquiry_point_email or "",
            "secretariat": self.secretariat or "",
            "website": str(self.website.url) or "",
            "website_status": self.website.status or "",
        }

    @field_validator("registered_contact_email", mode="before")
    def _fix_invalid_email(cls, v: str | EmailStr | None) -> Optional[EmailStr]:
        if v and "no email supplied" in v.lower():
            return None

        return v


class AGMDetails(BaseModel):
    date_of_most_recent_agm: Optional[date] = None
    published_income_expenditure_statement: bool = False
    reporting_year: Optional[str] = None
    next_reporting_deadline: Optional[date] = None

    # normalise Yes / No → bool for convenience
    @field_validator("published_income_expenditure_statement", mode="before")
    def _yn_to_bool(cls, v: str | bool | None) -> bool:
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        return v.strip().lower().startswith("y")


class APPG(BaseModel):
    slug: str
    title: str
    purpose: Optional[str] = None
    category: Optional[str] = None
    parliament: Parliament = Parliament.UK

    officers: List[Officer] = []
    members_list: MemberList = Field(default_factory=MemberList)
    contact_details: ContactDetails = ContactDetails(website=WebsiteSource())
    agm: Optional[AGMDetails] = None

    registrable_benefits: Optional[str] = None
    detailed_benefits: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of detailed benefits with structured data.",
    )

    index_date: str = ""
    source_url: Optional[HttpUrl] = None
    categories: list[AppgCategory] = Field(default_factory=list)

    def update_from(self, other: APPG):
        """
        Update elements that have been updated from other processes.
        Like members_list and the website (if it's not an official one in the new register).
        """
        self.members_list = other.members_list
        self.categories = other.categories
        if self.contact_details.website.status != "register":
            self.contact_details.website = other.contact_details.website
        return self

    def flattened_dict(self) -> dict[str, str]:
        """
        Flatten the APPG into a dictionary.
        """
        data = {
            "slug": self.slug,
            "title": self.title,
            "purpose": self.purpose or "",
            "category": self.category or "",
            "parliament": str(self.parliament),
            "registrable_benefits": self.registrable_benefits or "",
            "source_url": str(self.source_url) if self.source_url else "",
        }

        # Add detailed benefits data as a JSON string
        if self.detailed_benefits:
            data["detailed_benefits"] = dumps(self.detailed_benefits)

        data["categories"] = "|".join(self.categories)

        data.update(self.contact_details.flattened_dict())

        if self.agm:
            data.update(self.agm.model_dump())

        return data

    def has_website(self) -> bool:
        """
        Check if the APPG has a website.
        """
        if self.contact_details.website.url:
            return True
        else:
            return False

    @staticmethod
    def _get_parliament_folder(parliament: Parliament) -> str:
        """
        Get the folder name for a given parliament.
        """
        if parliament == Parliament.UK:
            return "appgs"
        elif parliament == Parliament.SENEDD_EN:
            return "cpg_senedd_en"
        elif parliament == Parliament.SENEDD_CY:
            return "cpg_senedd_cy"
        elif parliament == Parliament.SCOTLAND:
            return "cpg_scotland"
        elif parliament == Parliament.NI:
            return "apg_ni"
        else:
            raise ValueError(f"Unknown parliament: {parliament}")

    @classmethod
    def load(cls, slug: str, parliament: Parliament = Parliament.UK) -> APPG:
        """
        Load an APPG from a slug.
        """
        folder_name = cls._get_parliament_folder(parliament)
        base_folder = Path("data", folder_name)
        appg_file = base_folder / f"{slug}.json"

        if not appg_file.exists():
            raise FileNotFoundError(f"APPG file not found: {appg_file}")

        with appg_file.open("r", encoding="utf-8") as f:
            appg = cls.model_validate_json(f.read())
            appg.parliament = parliament  # Ensure parliament is set correctly
            return appg

    def save(self, release: str | None = None) -> None:
        """
        Save the APPG to a file.
        """
        if release:
            base_folder = Path("data", "raw", "releases", release)
        else:
            folder_name = self._get_parliament_folder(self.parliament)
            base_folder = Path("data", folder_name)
        appg_file = base_folder / f"{self.slug}.json"

        if not base_folder.exists():
            base_folder.mkdir(parents=True)

        with appg_file.open("w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))


class APPGList(RootModel):
    root: List[APPG]

    @classmethod
    def load(
        cls, release: str | None = None, parliament: Parliament = Parliament.UK
    ) -> APPGList:
        """
        Load all APPGs from the data folder.
        """
        if release:
            base_folder = Path("data", "raw", "releases", release)
        else:
            folder_name = APPG._get_parliament_folder(parliament)
            base_folder = Path("data", folder_name)

        appg_files = list(base_folder.glob("*.json"))

        appgs = []
        for appg_file in appg_files:
            with appg_file.open("r", encoding="utf-8") as f:
                appg = APPG.model_validate_json(f.read())
                appg.parliament = parliament  # Ensure parliament is set correctly
                appgs.append(appg)

        appgs.sort(key=lambda x: x.title.lower())

        return cls(root=appgs)

    @classmethod
    def load_all(cls, release: str | None = None) -> APPGList:
        """
        Load all APPGs from all parliament data folders and combine into a single list.
        """
        all_appgs = []

        for parliament in Parliament:
            try:
                appg_list = cls.load(release=release, parliament=parliament)
                all_appgs.extend(appg_list.root)
            except FileNotFoundError:
                # Parliament folder doesn't exist yet, skip it
                continue

        all_appgs.sort(key=lambda x: x.title.lower())
        return cls(root=all_appgs)

    def __len__(self) -> int:
        return len(self.root)

    def __iter__(self):
        return iter(self.root)


class NameCorrection(BaseModel):
    """
    A class to hold name corrections for APPGs.
    """

    original: str
    canon: str


class NameCorrectionList(RootModel):
    root: List[NameCorrection]

    def __iter__(self):
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def add_bad_names(self, bad_names: List[str]) -> None:
        """
        Add bad names to the list of name corrections.
        """
        keys = {item.original for item in self.root}
        for name in bad_names:
            if name not in keys:
                self.root.append(NameCorrection(original=name, canon=""))
        self.save()

    def as_dict(self) -> dict[str, str]:
        """
        Convert the name corrections to a dictionary.
        """
        return {item.original: item.canon.lower() for item in self.root if item.canon}

    def save(self) -> None:
        """
        Save the name corrections to a file.
        """
        path = Path("data", "raw", "mp_name_corrections.json")
        if not path.parent.exists():
            path.parent.mkdir(parents=True)

        with path.open("w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls) -> NameCorrectionList:
        """
        Load all name corrections from the data folder.
        """
        path = Path("data", "raw", "mp_name_corrections.json")
        if not path.exists():
            raise FileNotFoundError(f"Name corrections file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            return cls.model_validate_json(f.read())
