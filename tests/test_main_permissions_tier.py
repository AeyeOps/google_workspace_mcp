import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
from auth.permissions import set_permissions
from auth.scopes import CHAT_DELETE_SCOPE, CHAT_MEMBERSHIPS_SCOPE, CHAT_SPACES_SCOPE
from core import tool_registry


def test_resolve_permissions_mode_selection_without_tier():
    services = ["gmail", "drive"]
    resolved_services, tier_tool_filter = main.resolve_permissions_mode_selection(
        services, None
    )
    assert resolved_services == services
    assert tier_tool_filter is None


def test_resolve_permissions_mode_selection_with_tier_filters_services(monkeypatch):
    def fake_resolve_tools_from_tier(tier, services):
        assert tier == "core"
        assert services == ["gmail", "drive", "slides"]
        return ["search_gmail_messages"], ["gmail"]

    monkeypatch.setattr(main, "resolve_tools_from_tier", fake_resolve_tools_from_tier)

    resolved_services, tier_tool_filter = main.resolve_permissions_mode_selection(
        ["gmail", "drive", "slides"], "core"
    )
    assert resolved_services == ["gmail"]
    assert tier_tool_filter == {"search_gmail_messages"}


def test_narrow_permissions_to_services_keeps_selected_order():
    permissions = {"drive": "full", "gmail": "readonly", "calendar": "readonly"}
    narrowed = main.narrow_permissions_to_services(permissions, ["gmail", "drive"])
    assert narrowed == {"gmail": "readonly", "drive": "full"}


def test_narrow_permissions_to_services_drops_non_selected_services():
    permissions = {"gmail": "send", "drive": "full"}
    narrowed = main.narrow_permissions_to_services(permissions, ["gmail"])
    assert narrowed == {"gmail": "send"}


def test_permissions_and_tools_flags_are_rejected(monkeypatch, capsys):
    monkeypatch.setattr(main, "configure_safe_logging", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--permissions", "gmail:readonly", "--tools", "gmail"],
    )

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "--permissions and --tools cannot be combined" in captured.err


def test_chat_manage_filters_delete_space_tool_from_registered_surface():
    delete_tool = SimpleNamespace(
        fn=SimpleNamespace(
            _required_google_scopes=[CHAT_SPACES_SCOPE, CHAT_DELETE_SCOPE]
        )
    )
    create_tool = SimpleNamespace(
        fn=SimpleNamespace(
            _required_google_scopes=[CHAT_SPACES_SCOPE, CHAT_MEMBERSHIPS_SCOPE]
        )
    )

    class Provider:
        def __init__(self):
            self.removed = []
            self._components = {
                "tool:delete_space@v1": delete_tool,
                "tool:create_space@v1": create_tool,
            }

        def remove_tool(self, name):
            self.removed.append(name)

    provider = Provider()
    server = SimpleNamespace(local_provider=provider)

    set_permissions({"chat": "manage"})
    try:
        tool_registry.filter_server_tools(server)
    finally:
        set_permissions(None)

    assert provider.removed == ["delete_space"]


def test_chat_full_keeps_delete_space_tool_registered():
    delete_tool = SimpleNamespace(
        fn=SimpleNamespace(
            _required_google_scopes=[CHAT_SPACES_SCOPE, CHAT_DELETE_SCOPE]
        )
    )

    class Provider:
        def __init__(self):
            self.removed = []
            self._components = {"tool:delete_space@v1": delete_tool}

        def remove_tool(self, name):
            self.removed.append(name)

    provider = Provider()
    server = SimpleNamespace(local_provider=provider)

    set_permissions({"chat": "full"})
    try:
        tool_registry.filter_server_tools(server)
    finally:
        set_permissions(None)

    assert provider.removed == []


def test_main_skips_gcs_store_initialization_in_service_account_mode(monkeypatch):
    service_account_json = '{"type":"service_account","project_id":"p","private_key":"k","client_email":"svc@example.com"}'

    def fail_if_called():
        raise AssertionError("credential store should not be initialized")

    def fail_permission_check():
        raise AssertionError("local credential directory check should be skipped")

    def fake_run(*args, **kwargs):  # noqa: ARG001
        raise SystemExit(0)

    monkeypatch.setattr(main, "configure_safe_logging", lambda: None)
    monkeypatch.setattr(main, "import_module", lambda name: object())  # noqa: ARG005
    monkeypatch.setattr(main, "set_enabled_tool_names", lambda names: None)
    monkeypatch.setattr(main, "wrap_server_tool_method", lambda server: None)
    monkeypatch.setattr(main, "filter_server_tools", lambda server: None)
    monkeypatch.setattr(main, "set_transport_mode", lambda transport: None)
    monkeypatch.setattr(main, "get_selected_backend", lambda: "gcs")
    monkeypatch.setattr(main, "is_stateless_mode", lambda: False)
    monkeypatch.setattr(main, "is_service_account_enabled", lambda: True)
    monkeypatch.setattr(main, "get_credential_store", fail_if_called)
    monkeypatch.setattr(
        main, "check_credentials_directory_permissions", fail_permission_check
    )
    monkeypatch.setattr(
        main,
        "get_oauth_config",
        lambda: SimpleNamespace(
            service_account_key_file=None,
            service_account_key_json=service_account_json,
        ),
    )
    monkeypatch.setattr(main.server, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["main.py", "--tools", "gmail"])
    monkeypatch.setenv("USER_GOOGLE_EMAIL", "user@example.com")

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
