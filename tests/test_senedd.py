from pathlib import Path

from appg_membership.models import APPG, Member, MemberList, Parliament
from appg_membership.senedd import (
    clean_html_text,
    create_slug_from_name,
    determine_officer_role,
    parse_cpg_list,
    parse_detail_page_purpose,
    parse_detail_page_title,
    parse_members_list,
)

SCRAPED_PAGES_DIR = Path(__file__).parent.parent / "temp-scraped-pages"


class TestParliamentEnum:
    """Tests for the updated Parliament enum."""

    def test_senedd_en_value(self):
        assert Parliament.SENEDD_EN == "senedd-en"

    def test_senedd_cy_value(self):
        assert Parliament.SENEDD_CY == "senedd-cy"

    def test_all_parliament_values(self):
        values = [p.value for p in Parliament]
        assert "uk" in values
        assert "scotland" in values
        assert "senedd-en" in values
        assert "senedd-cy" in values

    def test_wales_not_in_enum(self):
        values = [p.value for p in Parliament]
        assert "wales" not in values


class TestParliamentFolder:
    """Tests for the parliament folder mapping."""

    def test_senedd_en_folder(self):
        folder = APPG._get_parliament_folder(Parliament.SENEDD_EN)
        assert folder == "cpg_senedd_en"

    def test_senedd_cy_folder(self):
        folder = APPG._get_parliament_folder(Parliament.SENEDD_CY)
        assert folder == "cpg_senedd_cy"

    def test_scotland_folder_unchanged(self):
        folder = APPG._get_parliament_folder(Parliament.SCOTLAND)
        assert folder == "cpg_scotland"

    def test_uk_folder_unchanged(self):
        folder = APPG._get_parliament_folder(Parliament.UK)
        assert folder == "appgs"


class TestMemberType:
    """Tests for the updated member_type literal."""

    def test_ms_member_type(self):
        member = Member(name="Test Member", member_type="ms")
        assert member.member_type == "ms"

    def test_existing_member_types_still_work(self):
        for member_type in ["mp", "lord", "msp", "other"]:
            member = Member(name="Test", member_type=member_type)
            assert member.member_type == member_type


class TestCleanHtmlText:
    """Tests for the clean_html_text utility."""

    def test_removes_tags(self):
        assert clean_html_text("<b>bold</b>") == "bold"

    def test_handles_br_tags(self):
        result = clean_html_text("line1<br/>line2")
        assert "line1" in result
        assert "line2" in result

    def test_unescapes_entities(self):
        assert clean_html_text("&amp;") == "&"
        assert clean_html_text("&lt;") == "<"

    def test_normalizes_whitespace(self):
        assert clean_html_text("  too   many   spaces  ") == "too many spaces"

    def test_collapses_newlines_to_spaces(self):
        assert clean_html_text("multi\n  line\n  text") == "multi line text"


class TestCreateSlug:
    """Tests for the Senedd slug creation."""

    def test_slug_from_cross_party_group_suffix(self):
        result = create_slug_from_name("Autism - Cross Party Group")
        assert result == "autism"

    def test_slug_multi_word_topic(self):
        result = create_slug_from_name(
            "Academic Staff in Universities - Cross Party Group"
        )
        assert result == "academic-staff-in-universities"

    def test_slug_with_ampersand(self):
        result = create_slug_from_name(
            "Co-operatives & Mutuals - Cross Party Group"
        )
        assert result == "co-operatives-mutuals"

    def test_slug_from_welsh_suffix(self):
        result = create_slug_from_name(
            "Staff Academaidd mewn Prifysgolion - Grŵp Trawsbleidiol"
        )
        assert result == "staff-academaidd-mewn-prifysgolion"

    def test_slug_lowercases(self):
        result = create_slug_from_name("Mental Health - Cross Party Group")
        assert result == "mental-health"


class TestParseCpgList:
    """Tests for parsing the CPG listing page."""

    def test_extracts_body_ids_and_names(self):
        html = """
        <ul class="mgBulletList">
            <li><a href="mgOutsideBodyDetails.aspx?ID=886"
                   title="Link to details">Academic Staff in Universities - Cross Party Group</a></li>
            <li><a href="mgOutsideBodyDetails.aspx?ID=790"
                   title="Link to details">Active Travel Act - Cross Party Group</a></li>
        </ul>
        """
        result = parse_cpg_list(html)
        assert len(result) == 2
        assert result[0]["id"] == "886"
        assert result[0]["name"] == "Academic Staff in Universities - Cross Party Group"
        assert result[1]["id"] == "790"

    def test_empty_page(self):
        html = "<html><body>No groups</body></html>"
        result = parse_cpg_list(html)
        assert len(result) == 0

    def test_real_listing_page(self):
        """Test parsing against real Senedd listing page HTML."""
        html = (SCRAPED_PAGES_DIR / "mgListOutsideBodiesByCategory.aspx").read_text()
        result = parse_cpg_list(html)
        assert len(result) == 85
        # Check first entry
        assert result[0]["id"] == "886"
        assert result[0]["name"] == "Academic Staff in Universities - Cross Party Group"
        # Check names don't have embedded newlines
        for entry in result:
            assert "\n" not in entry["name"]


class TestParseDetailPageTitle:
    """Tests for parsing the title from a detail page."""

    def test_mgSubTitleTxt(self):
        html = '<h2 class="mgSubTitleTxt">Academic Staff in Universities - Cross Party Group</h2>'
        assert (
            parse_detail_page_title(html)
            == "Academic Staff in Universities - Cross Party Group"
        )

    def test_plain_h1(self):
        html = "<h1>Some Title</h1>"
        assert parse_detail_page_title(html) == "Some Title"

    def test_no_title_returns_none(self):
        html = "<div>No title here</div>"
        assert parse_detail_page_title(html) is None

    def test_real_english_page_title(self):
        """Test title extraction from real English detail page."""
        html = (SCRAPED_PAGES_DIR / "mgOutsideBodyDetails-en").read_text()
        title = parse_detail_page_title(html)
        assert title == "Academic Staff in Universities - Cross Party Group"

    def test_real_welsh_page_title(self):
        """Test title extraction from real Welsh detail page."""
        html = (SCRAPED_PAGES_DIR / "msOutsideBodyDetails-cy").read_text()
        title = parse_detail_page_title(html)
        assert title == "Staff Academaidd mewn Prifysgolion - Grŵp Trawsbleidiol"


class TestParseDetailPagePurpose:
    """Tests for parsing the purpose from a detail page."""

    def test_no_purpose_returns_none(self):
        html = "<div>No purpose here</div>"
        assert parse_detail_page_purpose(html) is None

    def test_real_english_page_purpose(self):
        """Test purpose extraction from real English detail page."""
        html = (SCRAPED_PAGES_DIR / "mgOutsideBodyDetails-en").read_text()
        purpose = parse_detail_page_purpose(html)
        assert purpose is not None
        assert "universities" in purpose.lower()
        assert "academic freedom" in purpose.lower()
        # Should be clean text without newlines
        assert "\n" not in purpose

    def test_real_welsh_page_purpose(self):
        """Test purpose extraction from real Welsh detail page."""
        html = (SCRAPED_PAGES_DIR / "msOutsideBodyDetails-cy").read_text()
        purpose = parse_detail_page_purpose(html)
        assert purpose is not None
        assert "brifysgolion" in purpose.lower()
        assert "\n" not in purpose


class TestParseMembersList:
    """Tests for parsing the members list."""

    def test_basic_bullet_list(self):
        html = """
        <h2 class="mgSectionTitle">Members</h2>
        <ul  class="mgBulletList" >
            <li><a href="mgUserInfo.aspx?UID=332">Mike Hedges MS</a> &#40;Chair&#41; </li>
            <li><a href="mgUserInfo.aspx?UID=8670">Sioned Williams MS</a> &#40;Vice-Chair&#41; </li>
            <li><a href="mgUserInfo.aspx?UID=4983">Jane Dodds MS</a>  </li>
        </ul>
        """
        result = parse_members_list(html)
        assert len(result) == 3
        assert result[0]["name"] == "Mike Hedges MS"
        assert result[0]["role"] == "Chair"
        assert result[1]["name"] == "Sioned Williams MS"
        assert result[1]["role"] == "Vice-Chair"
        assert result[2]["name"] == "Jane Dodds MS"
        assert result[2]["role"] == ""

    def test_empty_list(self):
        html = """
        <h2 class="mgSectionTitle">Members</h2>
        <ul class="mgBulletList"></ul>
        """
        result = parse_members_list(html)
        assert len(result) == 0

    def test_no_members_section(self):
        html = "<div>No members here</div>"
        result = parse_members_list(html)
        assert len(result) == 0

    def test_real_english_members(self):
        """Test members extraction from real English detail page."""
        html = (SCRAPED_PAGES_DIR / "mgOutsideBodyDetails-en").read_text()
        members = parse_members_list(html)
        assert len(members) == 4
        # Check Chair
        assert members[0]["name"] == "Mike Hedges MS"
        assert members[0]["role"] == "Chair"
        # Check Vice-Chair
        assert members[1]["name"] == "Sioned Williams MS"
        assert members[1]["role"] == "Vice-Chair"
        # Check members without roles
        assert members[2]["name"] == "Jane Dodds MS"
        assert members[2]["role"] == ""
        assert members[3]["name"] == "Heledd Fychan MS"
        assert members[3]["role"] == ""

    def test_real_welsh_members(self):
        """Test members extraction from real Welsh detail page."""
        html = (SCRAPED_PAGES_DIR / "msOutsideBodyDetails-cy").read_text()
        members = parse_members_list(html)
        assert len(members) == 4
        # Check Welsh role names
        assert members[0]["name"] == "Mike Hedges AS"
        assert members[0]["role"] == "Cadeirydd"
        assert members[1]["name"] == "Sioned Williams AS"
        assert members[1]["role"] == "Is-Gadeirydd"


class TestDetermineOfficerRole:
    """Tests for officer role determination."""

    def test_chair_is_officer(self):
        assert determine_officer_role("Chair") is True

    def test_co_chair_is_officer(self):
        assert determine_officer_role("Co-Chair") is True

    def test_vice_chair_is_officer(self):
        assert determine_officer_role("Vice Chair") is True

    def test_vice_hyphen_chair_is_officer(self):
        assert determine_officer_role("Vice-Chair") is True

    def test_secretary_is_officer(self):
        assert determine_officer_role("Secretary") is True

    def test_member_is_not_officer(self):
        assert determine_officer_role("Member") is False

    def test_empty_role_is_not_officer(self):
        assert determine_officer_role("") is False

    def test_welsh_chair_is_officer(self):
        assert determine_officer_role("Cadeirydd") is True

    def test_welsh_vice_chair_is_officer(self):
        assert determine_officer_role("Is-Gadeirydd") is True

    def test_welsh_secretary_is_officer(self):
        assert determine_officer_role("Ysgrifennydd") is True


class TestAPPGSeneddIntegration:
    """Integration tests for APPG model with Senedd parliament values."""

    def test_create_senedd_en_appg(self):
        appg = APPG(
            slug="autism",
            title="Autism - Cross Party Group",
            purpose="To promote awareness of autism.",
            parliament=Parliament.SENEDD_EN,
        )
        assert appg.parliament == Parliament.SENEDD_EN
        assert str(appg.parliament) == "senedd-en"

    def test_create_senedd_cy_appg(self):
        appg = APPG(
            slug="autism",
            title="Awtistiaeth - Grŵp Trawsbleidiol",
            purpose="I hyrwyddo ymwybyddiaeth o awtistiaeth.",
            parliament=Parliament.SENEDD_CY,
        )
        assert appg.parliament == Parliament.SENEDD_CY
        assert str(appg.parliament) == "senedd-cy"

    def test_appg_serialization(self):
        appg = APPG(
            slug="autism",
            title="Autism - Cross Party Group",
            parliament=Parliament.SENEDD_EN,
        )
        data = appg.model_dump(mode="json")
        assert data["parliament"] == "senedd-en"

    def test_ms_member_in_appg(self):
        appg = APPG(
            slug="autism",
            title="Autism - Cross Party Group",
            parliament=Parliament.SENEDD_EN,
            members_list=MemberList(
                source_method="official",
                members=[
                    Member(name="Test MS", member_type="ms"),
                ],
            ),
        )
        assert appg.members_list.members[0].member_type == "ms"
