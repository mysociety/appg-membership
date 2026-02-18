from appg_membership.models import APPG, Member, MemberList, Parliament
from appg_membership.senedd import (
    clean_html_text,
    create_slug_from_name,
    determine_officer_role,
    parse_cpg_list,
    parse_detail_page_purpose,
    parse_detail_page_title,
    parse_members_table,
)


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


class TestCreateSlug:
    """Tests for the Senedd slug creation."""

    def test_basic_slug(self):
        assert create_slug_from_name("Cross-Party Group on Autism") == "autism"

    def test_slug_with_for(self):
        result = create_slug_from_name(
            "Cross-Party Group for Faith, Values and Ethics"
        )
        assert result == "faith-values-and-ethics"

    def test_slug_removes_the(self):
        result = create_slug_from_name("Cross-Party Group on the Armed Forces")
        assert result == "armed-forces"

    def test_slug_lowercases(self):
        result = create_slug_from_name("Cross-Party Group on Mental Health")
        assert result == "mental-health"

    def test_welsh_prefix_removal(self):
        result = create_slug_from_name("Grŵp Trawsbleidiol ar Awtistiaeth")
        assert result == "awtistiaeth"


class TestParseCpgList:
    """Tests for parsing the CPG listing page."""

    def test_extracts_body_ids_and_names(self):
        html = """
        <table>
            <tr><td><a href="mgOutsideBodyDetails.aspx?ID=886">Cross-Party Group on Autism</a></td></tr>
            <tr><td><a href="mgOutsideBodyDetails.aspx?ID=887">Cross-Party Group on Mental Health</a></td></tr>
        </table>
        """
        result = parse_cpg_list(html)
        assert len(result) == 2
        assert result[0]["id"] == "886"
        assert result[0]["name"] == "Cross-Party Group on Autism"
        assert result[1]["id"] == "887"

    def test_empty_page(self):
        html = "<html><body>No groups</body></html>"
        result = parse_cpg_list(html)
        assert len(result) == 0


class TestParseDetailPageTitle:
    """Tests for parsing the title from a detail page."""

    def test_h1_title(self):
        html = '<h1 class="mgMainTitleSpacer">Cross-Party Group on Autism</h1>'
        assert parse_detail_page_title(html) == "Cross-Party Group on Autism"

    def test_span_title(self):
        html = '<span id="lblTitle">Cross-Party Group on Mental Health</span>'
        assert parse_detail_page_title(html) == "Cross-Party Group on Mental Health"

    def test_plain_h1(self):
        html = "<h1>Some Title</h1>"
        assert parse_detail_page_title(html) == "Some Title"

    def test_no_title_returns_none(self):
        html = "<div>No title here</div>"
        assert parse_detail_page_title(html) is None


class TestParseDetailPagePurpose:
    """Tests for parsing the purpose from a detail page."""

    def test_lblNotes_span(self):
        html = '<span id="lblNotes">To promote awareness of autism.</span>'
        assert parse_detail_page_purpose(html) == "To promote awareness of autism."

    def test_divNotes_div(self):
        html = '<div id="divNotes">To support mental health initiatives.</div>'
        assert (
            parse_detail_page_purpose(html) == "To support mental health initiatives."
        )

    def test_no_purpose_returns_none(self):
        html = "<div>No purpose here</div>"
        assert parse_detail_page_purpose(html) is None


class TestParseMembersTable:
    """Tests for parsing the members table."""

    def test_basic_table(self):
        html = """
        <table>
            <tr><th>Name</th><th>Role</th></tr>
            <tr><td><a href="mgUserInfo.aspx?UID=1">John Smith MS</a></td><td>Chair</td></tr>
            <tr><td><a href="mgUserInfo.aspx?UID=2">Jane Doe MS</a></td><td>Member</td></tr>
        </table>
        """
        result = parse_members_table(html)
        assert len(result) == 2
        assert result[0]["name"] == "John Smith MS"
        assert result[0]["role"] == "Chair"
        assert result[1]["name"] == "Jane Doe MS"

    def test_no_link_names(self):
        html = """
        <table>
            <tr><th>Name</th><th>Role</th></tr>
            <tr><td>John Smith</td><td>Chair</td></tr>
        </table>
        """
        result = parse_members_table(html)
        assert len(result) == 1
        assert result[0]["name"] == "John Smith"

    def test_empty_table(self):
        html = """
        <table>
            <tr><th>Name</th><th>Role</th></tr>
        </table>
        """
        result = parse_members_table(html)
        assert len(result) == 0


class TestDetermineOfficerRole:
    """Tests for officer role determination."""

    def test_chair_is_officer(self):
        assert determine_officer_role("Chair") is True

    def test_co_chair_is_officer(self):
        assert determine_officer_role("Co-Chair") is True

    def test_vice_chair_is_officer(self):
        assert determine_officer_role("Vice Chair") is True

    def test_secretary_is_officer(self):
        assert determine_officer_role("Secretary") is True

    def test_member_is_not_officer(self):
        assert determine_officer_role("Member") is False

    def test_empty_role_is_not_officer(self):
        assert determine_officer_role("") is False

    def test_welsh_chair_is_officer(self):
        assert determine_officer_role("Cadeirydd") is True

    def test_welsh_secretary_is_officer(self):
        assert determine_officer_role("Ysgrifennydd") is True


class TestAPPGSeneddIntegration:
    """Integration tests for APPG model with Senedd parliament values."""

    def test_create_senedd_en_appg(self):
        appg = APPG(
            slug="autism",
            title="Cross-Party Group on Autism",
            purpose="To promote awareness of autism.",
            parliament=Parliament.SENEDD_EN,
        )
        assert appg.parliament == Parliament.SENEDD_EN
        assert str(appg.parliament) == "senedd-en"

    def test_create_senedd_cy_appg(self):
        appg = APPG(
            slug="autism",
            title="Grŵp Trawsbleidiol ar Awtistiaeth",
            purpose="I hyrwyddo ymwybyddiaeth o awtistiaeth.",
            parliament=Parliament.SENEDD_CY,
        )
        assert appg.parliament == Parliament.SENEDD_CY
        assert str(appg.parliament) == "senedd-cy"

    def test_appg_serialization(self):
        appg = APPG(
            slug="autism",
            title="Cross-Party Group on Autism",
            parliament=Parliament.SENEDD_EN,
        )
        data = appg.model_dump(mode="json")
        assert data["parliament"] == "senedd-en"

    def test_ms_member_in_appg(self):
        appg = APPG(
            slug="autism",
            title="Cross-Party Group on Autism",
            parliament=Parliament.SENEDD_EN,
            members_list=MemberList(
                source_method="official",
                members=[
                    Member(name="Test MS", member_type="ms"),
                ],
            ),
        )
        assert appg.members_list.members[0].member_type == "ms"
