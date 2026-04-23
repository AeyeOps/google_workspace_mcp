"""
Unit tests for Google Contacts (People API) tools.

Tests helper functions, formatting utilities, and read-only search surfaces.
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gcontacts.contacts_tools import (
    _format_contact,
    _build_person_body,
)


def _unwrap(tool):
    """Unwrap a FunctionTool + decorator chain to the original async function."""
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


class TestFormatContact:
    """Tests for _format_contact helper function."""

    def test_format_basic_contact(self):
        """Test formatting a contact with basic fields."""
        person = {
            "resourceName": "people/c1234567890",
            "names": [{"displayName": "John Doe"}],
            "emailAddresses": [{"value": "john@example.com"}],
            "phoneNumbers": [{"value": "+1234567890"}],
        }

        result = _format_contact(person)

        assert "Contact ID: c1234567890" in result
        assert "Name: John Doe" in result
        assert "Email: john@example.com" in result
        assert "Phone: +1234567890" in result

    def test_format_contact_with_organization(self):
        """Test formatting a contact with organization info."""
        person = {
            "resourceName": "people/c123",
            "names": [{"displayName": "Jane Smith"}],
            "organizations": [{"name": "Acme Corp", "title": "Engineer"}],
        }

        result = _format_contact(person)

        assert "Name: Jane Smith" in result
        assert "Organization: Engineer at Acme Corp" in result

    def test_format_contact_organization_name_only(self):
        """Test formatting a contact with only organization name."""
        person = {
            "resourceName": "people/c123",
            "organizations": [{"name": "Acme Corp"}],
        }

        result = _format_contact(person)

        assert "Organization: at Acme Corp" in result

    def test_format_contact_job_title_only(self):
        """Test formatting a contact with only job title."""
        person = {
            "resourceName": "people/c123",
            "organizations": [{"title": "CEO"}],
        }

        result = _format_contact(person)

        assert "Organization: CEO" in result

    def test_format_contact_detailed(self):
        """Test formatting a contact with detailed fields."""
        person = {
            "resourceName": "people/c123",
            "names": [{"displayName": "Test User"}],
            "addresses": [{"formattedValue": "123 Main St, City"}],
            "birthdays": [{"date": {"year": 1990, "month": 5, "day": 15}}],
            "urls": [{"value": "https://example.com"}],
            "biographies": [{"value": "A short bio"}],
            "metadata": {"sources": [{"type": "CONTACT"}]},
        }

        result = _format_contact(person, detailed=True)

        assert "Address: 123 Main St, City" in result
        assert "Birthday: 1990/5/15" in result
        assert "URLs: https://example.com" in result
        assert "Notes: A short bio" in result
        assert "Sources: CONTACT" in result

    def test_format_contact_detailed_birthday_without_year(self):
        """Test formatting birthday without year."""
        person = {
            "resourceName": "people/c123",
            "birthdays": [{"date": {"month": 5, "day": 15}}],
        }

        result = _format_contact(person, detailed=True)

        assert "Birthday: 5/15" in result

    def test_format_contact_detailed_long_biography(self):
        """Test formatting truncates long biographies."""
        long_bio = "A" * 300
        person = {
            "resourceName": "people/c123",
            "biographies": [{"value": long_bio}],
        }

        result = _format_contact(person, detailed=True)

        assert "Notes:" in result
        assert "..." in result
        assert len(result.split("Notes: ")[1].split("\n")[0]) <= 203  # 200 + "..."

    def test_format_contact_empty(self):
        """Test formatting a contact with minimal fields."""
        person = {"resourceName": "people/c999"}

        result = _format_contact(person)

        assert "Contact ID: c999" in result

    def test_format_contact_unknown_resource(self):
        """Test formatting a contact without resourceName."""
        person = {}

        result = _format_contact(person)

        assert "Contact ID: Unknown" in result

    def test_format_contact_multiple_emails(self):
        """Test formatting a contact with multiple emails."""
        person = {
            "resourceName": "people/c123",
            "emailAddresses": [
                {"value": "work@example.com"},
                {"value": "personal@example.com"},
            ],
        }

        result = _format_contact(person)

        assert "work@example.com" in result
        assert "personal@example.com" in result

    def test_format_contact_multiple_phones(self):
        """Test formatting a contact with multiple phone numbers."""
        person = {
            "resourceName": "people/c123",
            "phoneNumbers": [
                {"value": "+1111111111"},
                {"value": "+2222222222"},
            ],
        }

        result = _format_contact(person)

        assert "+1111111111" in result
        assert "+2222222222" in result

    def test_format_contact_multiple_urls(self):
        """Test formatting a contact with multiple URLs."""
        person = {
            "resourceName": "people/c123",
            "urls": [
                {"value": "https://linkedin.com/user"},
                {"value": "https://twitter.com/user"},
            ],
        }

        result = _format_contact(person, detailed=True)

        assert "https://linkedin.com/user" in result
        assert "https://twitter.com/user" in result


class TestBuildPersonBody:
    """Tests for _build_person_body helper function."""

    def test_build_basic_body(self):
        """Test building a basic person body."""
        body = _build_person_body(
            given_name="John",
            family_name="Doe",
            email="john@example.com",
        )

        assert body["names"][0]["givenName"] == "John"
        assert body["names"][0]["familyName"] == "Doe"
        assert body["emailAddresses"][0]["value"] == "john@example.com"

    def test_build_body_with_phone(self):
        """Test building a person body with phone."""
        body = _build_person_body(phone="+1234567890")

        assert body["phoneNumbers"][0]["value"] == "+1234567890"

    def test_build_body_with_organization(self):
        """Test building a person body with organization."""
        body = _build_person_body(
            given_name="Jane",
            organization="Acme Corp",
            job_title="Engineer",
        )

        assert body["names"][0]["givenName"] == "Jane"
        assert body["organizations"][0]["name"] == "Acme Corp"
        assert body["organizations"][0]["title"] == "Engineer"

    def test_build_body_organization_only(self):
        """Test building a person body with only organization name."""
        body = _build_person_body(organization="Acme Corp")

        assert body["organizations"][0]["name"] == "Acme Corp"
        assert "title" not in body["organizations"][0]

    def test_build_body_job_title_only(self):
        """Test building a person body with only job title."""
        body = _build_person_body(job_title="CEO")

        assert body["organizations"][0]["title"] == "CEO"
        assert "name" not in body["organizations"][0]

    def test_build_body_with_notes(self):
        """Test building a person body with notes."""
        body = _build_person_body(notes="Important contact")

        assert body["biographies"][0]["value"] == "Important contact"
        assert body["biographies"][0]["contentType"] == "TEXT_PLAIN"

    def test_build_body_with_address(self):
        """Test building a person body with address."""
        body = _build_person_body(address="123 Main St, City, State 12345")

        assert (
            body["addresses"][0]["formattedValue"] == "123 Main St, City, State 12345"
        )

    def test_build_empty_body(self):
        """Test building an empty person body."""
        body = _build_person_body()

        assert body == {}

    def test_build_body_given_name_only(self):
        """Test building a person body with only given name."""
        body = _build_person_body(given_name="John")

        assert body["names"][0]["givenName"] == "John"
        assert body["names"][0]["familyName"] == ""

    def test_build_body_family_name_only(self):
        """Test building a person body with only family name."""
        body = _build_person_body(family_name="Doe")

        assert body["names"][0]["givenName"] == ""
        assert body["names"][0]["familyName"] == "Doe"

    def test_build_full_body(self):
        """Test building a person body with all fields."""
        body = _build_person_body(
            given_name="John",
            family_name="Doe",
            email="john@example.com",
            phone="+1234567890",
            organization="Acme Corp",
            job_title="Engineer",
            notes="VIP contact",
            address="123 Main St",
        )

        assert body["names"][0]["givenName"] == "John"
        assert body["names"][0]["familyName"] == "Doe"
        assert body["emailAddresses"][0]["value"] == "john@example.com"
        assert body["phoneNumbers"][0]["value"] == "+1234567890"
        assert body["organizations"][0]["name"] == "Acme Corp"
        assert body["organizations"][0]["title"] == "Engineer"
        assert body["biographies"][0]["value"] == "VIP contact"
        assert body["addresses"][0]["formattedValue"] == "123 Main St"


class TestImports:
    """Tests to verify module imports work correctly."""

    def test_import_contacts_tools(self):
        """Test that contacts_tools module can be imported."""
        from gcontacts import contacts_tools

        assert hasattr(contacts_tools, "list_contacts")
        assert hasattr(contacts_tools, "get_contact")
        assert hasattr(contacts_tools, "search_contacts")
        assert hasattr(contacts_tools, "manage_contact")

    def test_import_group_tools(self):
        """Test that group tools can be imported."""
        from gcontacts import contacts_tools

        assert hasattr(contacts_tools, "list_contact_groups")
        assert hasattr(contacts_tools, "get_contact_group")
        assert hasattr(contacts_tools, "manage_contact_group")

    def test_import_directory_tools(self):
        """Test that directory and other-contacts tools can be imported."""
        from gcontacts import contacts_tools

        assert hasattr(contacts_tools, "search_directory_people")
        assert hasattr(contacts_tools, "list_other_contacts")
        assert hasattr(contacts_tools, "search_other_contacts")

    def test_import_batch_tools(self):
        """Test that batch tools can be imported."""
        from gcontacts import contacts_tools

        assert hasattr(contacts_tools, "manage_contacts_batch")


class TestConstants:
    """Tests for module constants."""

    def test_default_person_fields(self):
        """Test default person fields constant."""
        from gcontacts.contacts_tools import DEFAULT_PERSON_FIELDS

        assert "names" in DEFAULT_PERSON_FIELDS
        assert "emailAddresses" in DEFAULT_PERSON_FIELDS
        assert "phoneNumbers" in DEFAULT_PERSON_FIELDS
        assert "organizations" in DEFAULT_PERSON_FIELDS

    def test_detailed_person_fields(self):
        """Test detailed person fields constant."""
        from gcontacts.contacts_tools import DETAILED_PERSON_FIELDS

        assert "names" in DETAILED_PERSON_FIELDS
        assert "emailAddresses" in DETAILED_PERSON_FIELDS
        assert "addresses" in DETAILED_PERSON_FIELDS
        assert "birthdays" in DETAILED_PERSON_FIELDS
        assert "biographies" in DETAILED_PERSON_FIELDS

    def test_contact_group_fields(self):
        """Test contact group fields constant."""
        from gcontacts.contacts_tools import CONTACT_GROUP_FIELDS

        assert "name" in CONTACT_GROUP_FIELDS
        assert "groupType" in CONTACT_GROUP_FIELDS
        assert "memberCount" in CONTACT_GROUP_FIELDS


class TestReadOnlySearchTools:
    """Tests for read-only contact and directory search tools."""

    @pytest.mark.asyncio
    async def test_search_directory_people_formats_results(self):
        """Directory search should format People API directory results."""
        from gcontacts.contacts_tools import search_directory_people

        service = MagicMock()
        service.people.return_value.searchDirectoryPeople.return_value.execute.return_value = {
            "people": [
                {
                    "resourceName": "people/123",
                    "names": [{"displayName": "Lindsay Warner"}],
                    "emailAddresses": [{"value": "lindsay.warner@moodmedia.com"}],
                    "organizations": [{"name": "Mood Media", "title": "Director"}],
                    "metadata": {
                        "sources": [{"type": "DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"}]
                    },
                }
            ]
        }

        result = await _unwrap(search_directory_people)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
            query="lindsay",
        )

        assert "Directory Search Results for 'lindsay'" in result
        assert "Results in page: 1" in result
        assert "Name: Lindsay Warner" in result
        assert "lindsay.warner@moodmedia.com" in result
        assert "Organization: Director at Mood Media" in result

    @pytest.mark.asyncio
    async def test_list_other_contacts_formats_results(self):
        """Other contacts listing should format returned contacts."""
        from gcontacts.contacts_tools import list_other_contacts

        service = MagicMock()
        service.otherContacts.return_value.list.return_value.execute.return_value = {
            "otherContacts": [
                {
                    "resourceName": "people/other123",
                    "names": [{"displayName": "Anthony Example"}],
                    "emailAddresses": [{"value": "anthony@example.com"}],
                }
            ]
        }

        result = await _unwrap(list_other_contacts)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
            page_size=10,
        )

        assert "Other Contacts for steve.antonakakis@moodmedia.com" in result
        assert "Results in page: 1" in result
        assert "Total available: 1" in result
        assert "Name: Anthony Example" in result
        assert "anthony@example.com" in result

    @pytest.mark.asyncio
    async def test_search_other_contacts_formats_results(self):
        """Other contacts search should format returned matches."""
        from gcontacts.contacts_tools import search_other_contacts

        service = MagicMock()
        service.otherContacts.return_value.search.return_value.execute.return_value = {
            "results": [
                {
                    "person": {
                        "resourceName": "people/other999",
                        "names": [{"displayName": "Warner Search Hit"}],
                        "emailAddresses": [{"value": "warner@example.com"}],
                    }
                }
            ]
        }

        result = await _unwrap(search_other_contacts)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
            query="warner",
        )

        assert "Other Contact Search Results for 'warner'" in result
        assert "Results in page: 1" in result
        assert "Name: Warner Search Hit" in result
        assert "warner@example.com" in result

    @pytest.mark.asyncio
    async def test_search_directory_people_rejects_blank_sources(self):
        """Blank directory source strings should fail validation."""
        from gcontacts.contacts_tools import search_directory_people
        from core.utils import UserInputError

        service = MagicMock()

        with pytest.raises(
            UserInputError,
            match="sources must contain at least one non-empty directory source type",
        ):
            await _unwrap(search_directory_people)(
                service=service,
                user_google_email="steve.antonakakis@moodmedia.com",
                query="lindsay",
                sources=["   "],
            )

    @pytest.mark.asyncio
    async def test_search_directory_people_rejects_invalid_sources(self):
        """Unknown directory source literals should fail validation."""
        from gcontacts.contacts_tools import search_directory_people
        from core.utils import UserInputError

        service = MagicMock()

        with pytest.raises(UserInputError, match=r"Invalid directory source type\(s\): INVALID"):
            await _unwrap(search_directory_people)(
                service=service,
                user_google_email="steve.antonakakis@moodmedia.com",
                query="lindsay",
                sources=["INVALID"],
            )

    @pytest.mark.asyncio
    async def test_search_directory_people_empty_results_message(self):
        """Directory search should return a clear no-results message."""
        from gcontacts.contacts_tools import search_directory_people

        service = MagicMock()
        service.people.return_value.searchDirectoryPeople.return_value.execute.return_value = {}

        result = await _unwrap(search_directory_people)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
            query="lindsay",
        )

        assert result == "No directory people found matching 'lindsay' for steve.antonakakis@moodmedia.com."

    @pytest.mark.asyncio
    async def test_search_directory_people_renders_pagination_and_merge_sources(self):
        """Directory search should render next-page token and wire mergeSources."""
        from gcontacts.contacts_tools import search_directory_people

        service = MagicMock()
        service.people.return_value.searchDirectoryPeople.return_value.execute.return_value = {
            "people": [{"resourceName": "people/123", "names": [{"displayName": "Lindsay Warner"}]}],
            "nextPageToken": "dir-next-token",
        }

        result = await _unwrap(search_directory_people)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
            query="lindsay",
            merge_contact_data=True,
        )

        service.people.return_value.searchDirectoryPeople.assert_called_once()
        call_kwargs = service.people.return_value.searchDirectoryPeople.call_args.kwargs
        assert call_kwargs["mergeSources"] == ["DIRECTORY_MERGE_SOURCE_TYPE_CONTACT"]
        assert "Next page token: dir-next-token" in result

    @pytest.mark.asyncio
    async def test_list_other_contacts_empty_results_message(self):
        """Other contacts list should return a clear no-results message."""
        from gcontacts.contacts_tools import list_other_contacts

        service = MagicMock()
        service.otherContacts.return_value.list.return_value.execute.return_value = {}

        result = await _unwrap(list_other_contacts)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
        )

        assert result == "No other contacts found for steve.antonakakis@moodmedia.com."

    @pytest.mark.asyncio
    async def test_list_other_contacts_renders_pagination(self):
        """Other contacts list should render total and next-page token."""
        from gcontacts.contacts_tools import list_other_contacts

        service = MagicMock()
        service.otherContacts.return_value.list.return_value.execute.return_value = {
            "otherContacts": [{"resourceName": "people/other123", "names": [{"displayName": "Anthony Example"}]}],
            "totalSize": 23,
            "nextPageToken": "other-next-token",
        }

        result = await _unwrap(list_other_contacts)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
        )

        assert "Results in page: 1" in result
        assert "Total available: 23" in result
        assert "Next page token: other-next-token" in result

    @pytest.mark.asyncio
    async def test_search_other_contacts_empty_results_message(self):
        """Other contacts search should return a clear no-results message."""
        from gcontacts.contacts_tools import search_other_contacts

        service = MagicMock()
        service.otherContacts.return_value.search.return_value.execute.return_value = {}

        result = await _unwrap(search_other_contacts)(
            service=service,
            user_google_email="steve.antonakakis@moodmedia.com",
            query="warner",
        )

        assert result == "No other contacts found matching 'warner' for steve.antonakakis@moodmedia.com."
