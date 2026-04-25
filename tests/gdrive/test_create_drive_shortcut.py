"""
Unit tests for create_drive_shortcut tool.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gdrive.drive_tools import _create_drive_shortcut_impl as _raw_create_drive_shortcut


def _make_service(created_response):
    """Build a mock Drive service whose files().create().execute returns *created_response*."""
    execute = MagicMock(return_value=created_response)
    create = MagicMock()
    create.return_value.execute = execute
    files = MagicMock()
    files.return_value.create = create
    service = MagicMock()
    service.files = files
    return service


@pytest.mark.asyncio
async def test_create_shortcut_passes_correct_metadata():
    """Body must include shortcut mimeType and shortcutDetails.targetId."""
    api_response = {
        "id": "shortcut-id",
        "name": "Link to Report",
        "webViewLink": "https://drive.google.com/file/d/shortcut-id/view",
        "shortcutDetails": {
            "targetId": "target-id",
            "targetMimeType": "application/pdf",
        },
    }
    service = _make_service(api_response)

    with patch(
        "gdrive.drive_tools.resolve_folder_id",
        new_callable=AsyncMock,
        return_value="resolved-parent-id",
    ):
        result = await _raw_create_drive_shortcut(
            service,
            user_google_email="user@example.com",
            shortcut_name="Link to Report",
            target_file_id="target-id",
            parent_folder_id="some-parent",
        )

    service.files().create.assert_called_once_with(
        body={
            "name": "Link to Report",
            "mimeType": "application/vnd.google-apps.shortcut",
            "parents": ["resolved-parent-id"],
            "shortcutDetails": {"targetId": "target-id"},
        },
        fields="id, name, webViewLink, shortcutDetails(targetId, targetMimeType)",
        supportsAllDrives=True,
    )
    assert "shortcut-id" in result
    assert "Link to Report" in result
    assert "target-id" in result


@pytest.mark.asyncio
async def test_create_shortcut_root_parent():
    """Parent 'root' should still pass through resolve_folder_id."""
    api_response = {
        "id": "sc2",
        "name": "RootLink",
        "webViewLink": "https://drive.google.com/file/d/sc2/view",
        "shortcutDetails": {"targetId": "t2", "targetMimeType": "application/pdf"},
    }
    service = _make_service(api_response)

    with patch(
        "gdrive.drive_tools.resolve_folder_id",
        new_callable=AsyncMock,
        return_value="root",
    ) as mock_resolve:
        result = await _raw_create_drive_shortcut(
            service,
            user_google_email="user@example.com",
            shortcut_name="RootLink",
            target_file_id="t2",
            parent_folder_id="root",
        )

    mock_resolve.assert_awaited_once_with(service, "root")
    assert "sc2" in result
    assert "RootLink" in result


@pytest.mark.asyncio
async def test_create_shortcut_missing_webviewlink():
    """When API omits webViewLink, result should still include id and name."""
    api_response = {
        "id": "sc3",
        "name": "NoLink",
        "shortcutDetails": {"targetId": "t3", "targetMimeType": "application/pdf"},
    }
    service = _make_service(api_response)

    with patch(
        "gdrive.drive_tools.resolve_folder_id",
        new_callable=AsyncMock,
        return_value="root",
    ):
        result = await _raw_create_drive_shortcut(
            service,
            user_google_email="user@example.com",
            shortcut_name="NoLink",
            target_file_id="t3",
            parent_folder_id="root",
        )

    assert "sc3" in result
    assert "NoLink" in result
