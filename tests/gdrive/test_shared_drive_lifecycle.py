"""Unit tests for Shared Drive lifecycle tools."""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gdrive.drive_tools import (
    SHARED_DRIVE_FIELDS,
    create_shared_drive,
    delete_shared_drive,
    get_shared_drive,
    hide_shared_drive,
    list_shared_drives,
    unhide_shared_drive,
    update_shared_drive,
)


def _unwrap(tool):
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _service_for(method_name, response):
    execute = Mock(return_value=response)
    method = Mock()
    method.return_value.execute = execute
    drives = Mock()
    getattr(drives.return_value, method_name).return_value = method.return_value
    service = Mock()
    service.drives = drives
    return service


@pytest.mark.asyncio
async def test_list_shared_drives_passes_query_pagination_and_admin_access():
    service = _service_for(
        "list",
        {
            "drives": [
                {
                    "id": "drive-1",
                    "name": "Engineering",
                    "createdTime": "2026-01-01T00:00:00Z",
                    "hidden": False,
                    "capabilities": {"canManageMembers": True},
                    "restrictions": {"driveMembersOnly": True},
                }
            ],
            "nextPageToken": "next-token",
        },
    )

    result = await _unwrap(list_shared_drives)(
        service=service,
        user_google_email="user@example.com",
        page_size=25,
        page_token="page-token",
        query="name contains 'Eng'",
        use_domain_admin_access=True,
    )

    service.drives.return_value.list.assert_called_once()
    kwargs = service.drives.return_value.list.call_args.kwargs
    assert kwargs["pageSize"] == 25
    assert kwargs["pageToken"] == "page-token"
    assert kwargs["q"] == "name contains 'Eng'"
    assert kwargs["useDomainAdminAccess"] is True
    assert kwargs["fields"] == f"nextPageToken, drives({SHARED_DRIVE_FIELDS})"
    assert "drive-1" in result
    assert "Engineering" in result
    assert "capabilities" in result
    assert "restrictions" in result
    assert result.endswith("nextPageToken: next-token")


@pytest.mark.asyncio
async def test_get_shared_drive_call_shape_and_output():
    service = _service_for(
        "get",
        {
            "id": "drive-1",
            "name": "Engineering",
            "hidden": False,
            "createdTime": "2026-01-01T00:00:00Z",
        },
    )

    result = await _unwrap(get_shared_drive)(
        service=service,
        user_google_email="user@example.com",
        drive_id="drive-1",
        use_domain_admin_access=True,
    )

    service.drives.return_value.get.assert_called_once()
    kwargs = service.drives.return_value.get.call_args.kwargs
    assert kwargs["driveId"] == "drive-1"
    assert kwargs["useDomainAdminAccess"] is True
    assert kwargs["fields"] == SHARED_DRIVE_FIELDS
    assert "Engineering" in result
    assert "createdTime" in result


@pytest.mark.asyncio
async def test_create_shared_drive_uses_provided_request_id_and_drive_scope_call_shape():
    service = _service_for(
        "create",
        {
            "id": "drive-1",
            "name": "MM GH Repo Large Items",
            "createdTime": "2026-01-01T00:00:00Z",
        },
    )

    result = await _unwrap(create_shared_drive)(
        service=service,
        user_google_email="user@example.com",
        drive_name="MM GH Repo Large Items",
        request_id="req-123",
    )

    service.drives.return_value.create.assert_called_once_with(
        requestId="req-123",
        body={"name": "MM GH Repo Large Items"},
        fields=SHARED_DRIVE_FIELDS,
    )
    assert "Successfully created Shared Drive" in result
    assert "req-123" in result
    assert "drive-1" in result
    assert "webViewLink: https://drive.google.com/drive/folders/drive-1" in result


@pytest.mark.asyncio
async def test_create_shared_drive_generates_uuid_request_id_when_missing():
    service = _service_for("create", {"id": "drive-1", "name": "Generated"})

    with patch("gdrive.drive_tools.uuid.uuid4", return_value="generated-uuid"):
        await _unwrap(create_shared_drive)(
            service=service,
            user_google_email="user@example.com",
            drive_name="Generated",
        )

    assert service.drives.return_value.create.call_args.kwargs["requestId"] == "generated-uuid"


@pytest.mark.asyncio
async def test_update_shared_drive_builds_patch_body_with_restrictions():
    service = _service_for(
        "update",
        {
            "id": "drive-1",
            "name": "New Name",
            "hidden": False,
            "restrictions": {"domainUsersOnly": True},
        },
    )

    result = await _unwrap(update_shared_drive)(
        service=service,
        user_google_email="user@example.com",
        drive_id="drive-1",
        drive_name="New Name",
        color_rgb="#3367d6",
        restrictions={"domainUsersOnly": True},
        use_domain_admin_access=True,
    )

    service.drives.return_value.update.assert_called_once()
    kwargs = service.drives.return_value.update.call_args.kwargs
    assert kwargs["driveId"] == "drive-1"
    assert kwargs["body"] == {
        "name": "New Name",
        "colorRgb": "#3367d6",
        "restrictions": {"domainUsersOnly": True},
    }
    assert kwargs["useDomainAdminAccess"] is True
    assert "restrictions" in result


@pytest.mark.asyncio
async def test_update_shared_drive_requires_a_patch_field():
    service = _service_for("update", {})

    with pytest.raises(ValueError, match="requires at least one"):
        await _unwrap(update_shared_drive)(
            service=service,
            user_google_email="user@example.com",
            drive_id="drive-1",
        )

    service.drives.return_value.update.assert_not_called()


@pytest.mark.asyncio
async def test_hide_shared_drive_call_shape():
    service = _service_for("hide", {"id": "drive-1", "name": "Hidden", "hidden": True})

    result = await _unwrap(hide_shared_drive)(
        service=service,
        user_google_email="user@example.com",
        drive_id="drive-1",
    )

    service.drives.return_value.hide.assert_called_once()
    assert service.drives.return_value.hide.call_args.kwargs == {
        "driveId": "drive-1",
        "fields": SHARED_DRIVE_FIELDS,
    }
    assert "Successfully hid" in result
    assert "hidden: True" in result


@pytest.mark.asyncio
async def test_unhide_shared_drive_call_shape():
    service = _service_for("unhide", {"id": "drive-1", "name": "Visible", "hidden": False})

    result = await _unwrap(unhide_shared_drive)(
        service=service,
        user_google_email="user@example.com",
        drive_id="drive-1",
    )

    service.drives.return_value.unhide.assert_called_once()
    assert service.drives.return_value.unhide.call_args.kwargs == {
        "driveId": "drive-1",
        "fields": SHARED_DRIVE_FIELDS,
    }
    assert "Successfully unhid" in result
    assert "hidden: False" in result


@pytest.mark.asyncio
async def test_delete_shared_drive_omits_allow_item_deletion_by_default():
    service = _service_for("delete", {})

    result = await _unwrap(delete_shared_drive)(
        service=service,
        user_google_email="user@example.com",
        drive_id="drive-1",
    )

    service.drives.return_value.delete.assert_called_once_with(
        driveId="drive-1",
        useDomainAdminAccess=False,
    )
    assert "Successfully deleted" in result


@pytest.mark.asyncio
async def test_delete_shared_drive_can_pass_admin_allow_item_deletion():
    service = _service_for("delete", {})

    await _unwrap(delete_shared_drive)(
        service=service,
        user_google_email="user@example.com",
        drive_id="drive-1",
        use_domain_admin_access=True,
        allow_item_deletion=True,
    )

    service.drives.return_value.delete.assert_called_once_with(
        driveId="drive-1",
        useDomainAdminAccess=True,
        allowItemDeletion=True,
    )
