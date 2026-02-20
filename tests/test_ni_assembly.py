from appg_membership.models import APPG, Member, MemberList, Parliament
from appg_membership.ni_assembly import (
    NIAllMembersRolesResponse,
    NIMemberRole,
    NIOrganisation,
    NIOrganisationsResponse,
    PascalModel,
    create_slug_from_name,
    determine_officer_role,
    lookup_twfy_id,
    normalise_role_name,
    scrape_benefits_from_detail_page,
    scrape_purpose_from_detail_page,
)


class TestParliamentEnumNI:
    """Tests for the NI addition to the Parliament enum."""

    def test_ni_value(self):
        assert Parliament.NI == "ni"

    def test_all_parliament_values_include_ni(self):
        values = [p.value for p in Parliament]
        assert "ni" in values

    def test_ni_folder(self):
        folder = APPG._get_parliament_folder(Parliament.NI)
        assert folder == "apg_ni"


class TestMemberTypeMLA:
    """Tests for the MLA member type."""

    def test_mla_member_type(self):
        member = Member(name="Test MLA", member_type="mla")
        assert member.member_type == "mla"

    def test_existing_member_types_still_work(self):
        for member_type in ["mp", "lord", "msp", "ms", "other"]:
            member = Member(name="Test", member_type=member_type)
            assert member.member_type == member_type


class TestCreateSlugNI:
    """Tests for NI Assembly slug creation."""

    def test_slug_from_standard_name(self):
        result = create_slug_from_name("All-Party Group on Access to Justice")
        assert result == "access-to-justice"

    def test_slug_from_multi_word_topic(self):
        result = create_slug_from_name("All-Party Group on Artificial Intelligence")
        assert result == "artificial-intelligence"

    def test_slug_strips_leading_the(self):
        result = create_slug_from_name("All-Party Group on the Armed Forces")
        assert result == "armed-forces"

    def test_slug_lowercases(self):
        result = create_slug_from_name("All-Party Group on Food to Go")
        assert result == "food-to-go"

    def test_slug_with_special_chars(self):
        result = create_slug_from_name(
            "All-Party Group on Science, Technology, Engineering and Mathematics"
        )
        assert result == "science-technology-engineering-and-mathematics"

    def test_slug_ethnic_minority(self):
        result = create_slug_from_name("All-Party Group on Ethnic Minority Community")
        assert result == "ethnic-minority-community"


class TestDetermineOfficerRoleNI:
    """Tests for NI Assembly officer role determination."""

    def test_chairperson_is_officer(self):
        assert determine_officer_role("Assembly Party Group Chairperson") is True

    def test_vice_chairperson_is_officer(self):
        assert determine_officer_role("Assembly Party Group Vice-Chairperson") is True

    def test_secretary_is_officer(self):
        assert determine_officer_role("Assembly Party Group Secretary") is True

    def test_treasurer_is_officer(self):
        assert determine_officer_role("Assembly Party Group Treasurer") is True

    def test_member_is_not_officer(self):
        assert determine_officer_role("Assembly Party Group Member") is False

    def test_empty_role_is_not_officer(self):
        assert determine_officer_role("") is False

    def test_case_insensitive(self):
        assert determine_officer_role("assembly party group chairperson") is True


class TestNormaliseRoleName:
    """Tests for normalising NI Assembly role names."""

    def test_chairperson(self):
        assert normalise_role_name("Assembly Party Group Chairperson") == "Chairperson"

    def test_vice_chairperson(self):
        assert (
            normalise_role_name("Assembly Party Group Vice-Chairperson")
            == "Vice-Chairperson"
        )

    def test_secretary(self):
        assert normalise_role_name("Assembly Party Group Secretary") == "Secretary"

    def test_member(self):
        assert normalise_role_name("Assembly Party Group Member") == "Member"


class TestPascalModel:
    """Tests for the PascalModel alias generator."""

    def test_alias_generator_converts_snake_to_pascal(self):
        """Verify the alias generator maps PascalCase JSON keys to snake_case fields."""
        data = {
            "OrganisationId": "123",
            "OrganisationName": "Test Group",
            "OrganisationType": "All Party Group",
        }
        org = NIOrganisation.model_validate(data)
        assert org.organisation_id == "123"

    def test_pascal_model_is_base_class(self):
        assert issubclass(NIOrganisation, PascalModel)
        assert issubclass(NIMemberRole, PascalModel)


class TestNIOrganisationModels:
    """Tests for NI Assembly pydantic data models."""

    def test_parse_organisation(self):
        data = {
            "OrganisationId": "2185",
            "OrganisationName": "All-Party Group on Access to Justice",
            "OrganisationType": "All Party Group",
        }
        org = NIOrganisation.model_validate(data)
        assert org.organisation_id == "2185"
        assert org.organisation_name == "All-Party Group on Access to Justice"
        assert org.organisation_type == "All Party Group"

    def test_parse_organisations_response(self):
        data = {
            "OrganisationsList": {
                "Organisation": [
                    {
                        "OrganisationId": "2185",
                        "OrganisationName": "All-Party Group on Access to Justice",
                        "OrganisationType": "All Party Group",
                    },
                    {
                        "OrganisationId": "2458",
                        "OrganisationName": "All-Party Group on Artificial Intelligence",
                        "OrganisationType": "All Party Group",
                    },
                ]
            }
        }
        response = NIOrganisationsResponse.model_validate(data)
        orgs = response.organisations_list.organisation
        assert len(orgs) == 2
        assert orgs[0].organisation_id == "2185"
        assert orgs[1].organisation_name == "All-Party Group on Artificial Intelligence"

    def test_parse_member_role(self):
        data = {
            "PersonId": "5797",
            "AffiliationId": "22923",
            "MemberFullDisplayName": "Dr Steve Aiken OBE",
            "RoleType": "All Party Group Role",
            "Role": "Assembly Party Group Secretary",
            "OrganisationId": "2458",
            "Organisation": "All-Party Group on Artificial Intelligence",
            "AffiliationStart": "2025-10-22T00:00:00+01:00",
            "AffiliationTitle": "Assembly Party Group Secretary",
        }
        role = NIMemberRole.model_validate(data)
        assert role.person_id == "5797"
        assert role.member_full_display_name == "Dr Steve Aiken OBE"
        assert role.role_type == "All Party Group Role"
        assert role.role == "Assembly Party Group Secretary"
        assert role.organisation_id == "2458"

    def test_parse_all_members_roles_response(self):
        data = {
            "AllMembersRoles": {
                "Role": [
                    {
                        "PersonId": "5797",
                        "AffiliationId": "22923",
                        "MemberFullDisplayName": "Dr Steve Aiken OBE",
                        "RoleType": "All Party Group Role",
                        "Role": "Assembly Party Group Secretary",
                        "OrganisationId": "2458",
                        "Organisation": "All-Party Group on Artificial Intelligence",
                        "AffiliationStart": "2025-10-22T00:00:00+01:00",
                        "AffiliationTitle": "Assembly Party Group Secretary",
                    },
                    {
                        "PersonId": "5307",
                        "AffiliationId": "22554",
                        "MemberFullDisplayName": "Mr Andy Allen MBE",
                        "RoleType": "All Party Group Role",
                        "Role": "Assembly Party Group Member",
                        "OrganisationId": "2247",
                        "Organisation": "All-Party Group on Aerospace and Space",
                        "AffiliationStart": "2025-07-02T00:00:00+01:00",
                        "AffiliationTitle": "Assembly Party Group Member",
                    },
                ]
            }
        }
        response = NIAllMembersRolesResponse.model_validate(data)
        roles = response.all_members_roles.role
        assert len(roles) == 2
        assert roles[0].person_id == "5797"
        assert roles[1].member_full_display_name == "Mr Andy Allen MBE"


class TestScrapePurpose:
    """Tests for scraping purpose from NI Assembly detail pages."""

    def test_extracts_purpose(self):
        html = """
        <div class="synopsis">
            <div class="field-item">
                Purpose: To promote access to justice for all.
            </div>
        </div>
        """
        result = scrape_purpose_from_detail_page(html)
        assert result == "To promote access to justice for all."

    def test_no_purpose_returns_none(self):
        html = "<div>No purpose here</div>"
        result = scrape_purpose_from_detail_page(html)
        assert result is None

    def test_strips_html_tags(self):
        html = """
        <div id="ctl00_MainContentPlaceHolder_AccordionPane0_content">
            <div class="border-box">
                <p><strong>To promote</strong> access to <em>justice</em>.</p>
            </div>
        </div>
        """
        result = scrape_purpose_from_detail_page(html)
        assert result == "To promote access to justice."

    def test_converts_bullet_points_to_semicolons(self):
        html = """
        <div class="synopsis">
            <div class="field-item">
                Purpose: • First objective • Second objective • Third objective
            </div>
        </div>
        """
        result = scrape_purpose_from_detail_page(html)
        assert result == "First objective; Second objective; Third objective"


class TestScrapeBenefits:
    """Tests for scraping financial benefits from NI Assembly detail pages."""

    def test_extracts_table_without_javascript_noise(self):
        html = """
        <div id="ctl00_MainContentPlaceHolder_AccordionPane1_content" style="display:none;">
            <table id="ctl00_MainContentPlaceHolder_AccordionPane1_content_APGFinanceGridView">
                <tr><th>Date</th><th>Amount</th><th>Source</th><th>Description</th></tr>
                <tr><td>13/05/2025</td><td>&gt;&#163;250 p.a.</td><td>The Bar</td><td>Secretariat Support</td></tr>
            </table>
        </div>
        <script>
            $('table').each(function () { console.log('js should not be captured'); });
        </script>
        """
        result = scrape_benefits_from_detail_page(html)
        assert (
            result
            == "Date Amount Source Description 13/05/2025 >£250 p.a. The Bar Secretariat Support"
        )

    def test_extracts_no_finance_message(self):
        html = """
        <div id="ctl00_MainContentPlaceHolder_AccordionPane1_content_NoFinance">
            There have been no financial or other benefits received by this committee
        </div>
        """
        result = scrape_benefits_from_detail_page(html)
        assert (
            result
            == "There have been no financial or other benefits received by this committee"
        )

    def test_no_benefits_returns_none(self):
        html = "<div>No benefits here</div>"
        result = scrape_benefits_from_detail_page(html)
        assert result is None


class TestAPPGNIIntegration:
    """Integration tests for APPG model with NI parliament values."""

    def test_create_ni_appg(self):
        appg = APPG(
            slug="access-to-justice",
            title="All-Party Group on Access to Justice",
            purpose="To promote access to justice.",
            parliament=Parliament.NI,
        )
        assert appg.parliament == Parliament.NI
        assert str(appg.parliament) == "ni"

    def test_appg_serialization(self):
        appg = APPG(
            slug="access-to-justice",
            title="All-Party Group on Access to Justice",
            parliament=Parliament.NI,
        )
        data = appg.model_dump(mode="json")
        assert data["parliament"] == "ni"

    def test_mla_member_in_appg(self):
        appg = APPG(
            slug="access-to-justice",
            title="All-Party Group on Access to Justice",
            parliament=Parliament.NI,
            members_list=MemberList(
                source_method="official",
                members=[
                    Member(name="Dr Steve Aiken OBE", member_type="mla"),
                ],
            ),
        )
        assert appg.members_list.members[0].member_type == "mla"
        assert appg.members_list.members[0].name == "Dr Steve Aiken OBE"


class TestLookupTwfyId:
    """Tests for NI Assembly person ID to TWFY ID conversion."""

    def test_returns_none_when_no_popolo(self):
        assert lookup_twfy_id("5797", None) is None

    def test_returns_none_for_empty_person_id(self):
        assert lookup_twfy_id("", None) is None

    def test_returns_none_for_unknown_id(self):
        class FakePopolo:
            class persons:
                @staticmethod
                def from_identifier(id, scheme):
                    raise KeyError(f"Unknown id: {id}")

        assert lookup_twfy_id("999999", FakePopolo()) is None

    def test_returns_twfy_id_for_known_id(self):
        class FakePerson:
            id = "uk.org.publicwhip/person/25000"

        class FakePopolo:
            class persons:
                @staticmethod
                def from_identifier(id, scheme):
                    if id == "5797":
                        return FakePerson()
                    raise KeyError(f"Unknown id: {id}")

        result = lookup_twfy_id("5797", FakePopolo())
        assert result == "uk.org.publicwhip/person/25000"
