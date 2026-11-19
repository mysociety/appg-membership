from pathlib import Path

from bs4 import BeautifulSoup

from appg_membership.fetch_index import parse_appg_html
from appg_membership.models import APPG

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "register_pages"
    / "extraordinary-rendition.htm"
)


def _financial_benefit(
    source: str, value: str, received: str, registered: str
) -> dict[str, str]:
    return {
        "Source": source,
        "Value £s": value,
        "Received": received,
        "Registered": registered,
        "benefit_type": "Financial Benefits",
    }


JRCT = "Joseph Rowntree Charitable Trust"

FINANCIAL_BENEFITS = [
    _financial_benefit(JRCT, "15,000", "01/01/2025", "24/10/2025"),
    _financial_benefit(JRCT, "15,000", "01/04/2025", "24/10/2025"),
    _financial_benefit(JRCT, "15,000", "02/07/2025", "24/10/2025"),
    _financial_benefit(
        "APPG on Extraordinary Rendition in the previous Parliament",
        "66,144",
        "03/12/2024",
        "12/12/2025",
    ),
    _financial_benefit(JRCT, "15,000", "01/10/2025", "15/12/2025"),
    _financial_benefit(JRCT, "15,000", "01/01/2026", "12/06/2026"),
    _financial_benefit(JRCT, "15,000", "01/04/2026", "12/06/2026"),
]

IN_KIND_BENEFIT = {
    "Source": "Freshfields",
    "Description": "Legal assistance From: 03/12/2024 To: 02/12/2025",
    "Value £s In bands of £1,500": "108,001-109,500",
    "Received": "03/12/2024",
    "Registered": "12/12/2025",
    "benefit_type": "Benefits In Kind",
}


def _parse(html: str) -> APPG:
    return parse_appg_html(
        html,
        slug="extraordinary-rendition",
        source_url="https://publications.parliament.uk/pa/cm/cmallparty/261012/extraordinary-rendition.htm",
        index_date="261012",
    )


def _page_without(*, financial: bool = False, in_kind: bool = False) -> str:
    """
    Return the fixture page with its financial and/or in-kind benefits removed.
    """
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "lxml")
    *_, benefits_table, in_kind_table = soup.find_all("table", class_="basicTable")
    if financial:
        # Keep only the "Registrable benefits received by the group" title row
        for row in benefits_table.find_all("tr")[1:]:
            row.decompose()
    if in_kind:
        in_kind_table.decompose()
    return str(soup)


class TestRegistrableBenefits:
    """Tests for parsing registrable benefits from a UK register page."""

    def test_financial_and_in_kind_benefits_are_all_parsed(self):
        appg = _parse(FIXTURE.read_text(encoding="utf-8"))
        assert appg.detailed_benefits == FINANCIAL_BENEFITS + [IN_KIND_BENEFIT]

    def test_registrable_benefits_unchanged(self):
        appg = _parse(FIXTURE.read_text(encoding="utf-8"))
        assert appg.registrable_benefits == "Financial Benefits"

    def test_financial_only_page(self):
        appg = _parse(_page_without(in_kind=True))
        assert appg.registrable_benefits == "Financial Benefits"
        assert appg.detailed_benefits == FINANCIAL_BENEFITS

    def test_in_kind_only_page(self):
        appg = _parse(_page_without(financial=True))
        assert appg.registrable_benefits == "Benefits In Kind"
        assert appg.detailed_benefits == [IN_KIND_BENEFIT]

    def test_no_benefits_page(self):
        appg = _parse(_page_without(financial=True, in_kind=True))
        assert appg.registrable_benefits is None
        assert appg.detailed_benefits == []
