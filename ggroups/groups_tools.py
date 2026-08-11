"""
Google Groups MCP Tools (Cloud Identity Groups API)

Group membership is the authorization substrate behind Workspace SSO: an
identity provider replicates these groups, and an application decides what a
person may do from the group names in the token. Answering "who can reach
this app" therefore means reading groups, which the People/Directory surface
cannot do — it exposes people, not the groups that gate them.

The Cloud Identity API addresses a group two ways. The caller supplies the
group's email address; every other call needs the server-assigned resource
name (``groups/<id>``), which only a lookup returns. These tools take the
email throughout and resolve it internally.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from mcp import Resource

from auth.service_decorator import require_google_service
from core.server import server
from core.utils import UserInputError, handle_http_errors

logger = logging.getLogger(__name__)

# Cloud Identity splits its surface by "view". FULL carries the dynamic
# membership and security-label detail BASIC omits.
GROUP_VIEW_FULL = "FULL"

# The discussion-forum label is what distinguishes a Google Group from the
# other things Cloud Identity models as groups (security groups, dynamic
# groups). Search and list calls must name it or they return nothing.
DISCUSSION_FORUM_LABEL = "cloudidentity.googleapis.com/groups.discussion_forum"


def _customer_query(customer_id: str) -> str:
    return f"parent == 'customers/{customer_id}' && '{DISCUSSION_FORUM_LABEL}' in labels"


def _format_group(group: Dict[str, Any]) -> str:
    name = group.get("displayName") or "(no display name)"
    email = group.get("groupKey", {}).get("id", "(no address)")
    resource = group.get("name", "")
    desc = (group.get("description") or "").strip()
    line = f"- {name}\n  address: {email}\n  resource: {resource}"
    if desc:
        line += f"\n  description: {desc}"
    return line


def _format_membership(member: Dict[str, Any]) -> str:
    email = member.get("preferredMemberKey", {}).get("id", "(unknown)")
    roles = ", ".join(sorted(r.get("name", "") for r in member.get("roles", []))) or "MEMBER"
    return f"- {email}  [{roles}]"


async def _resolve_group_name(service: Resource, group_email: str) -> str:
    """Return the ``groups/<id>`` resource name for a group address."""
    result = await asyncio.to_thread(
        service.groups().lookup(groupKey_id=group_email).execute
    )
    name = result.get("name")
    if not name:
        raise UserInputError(f"No group found for address {group_email}.")
    return name


@server.tool()
@require_google_service("cloudidentity", "groups_read")
@handle_http_errors("search_groups", service_type="cloudidentity")
async def search_groups(
    service: Resource,
    user_google_email: str,
    customer_id: str = "my_customer",
    query: Optional[str] = None,
    page_size: int = 200,
    page_token: Optional[str] = None,
) -> str:
    """
    List Google Groups in the Workspace account, optionally filtered by name.

    Args:
        user_google_email (str): The user's Google email address. Required.
        customer_id (str): Workspace customer ID, or "my_customer" for the caller's own.
        query (Optional[str]): Case-insensitive substring matched against display name and address.
        page_size (int): Maximum groups to return per page (default 200, max 500).
        page_token (Optional[str]): Token for pagination.

    Returns:
        str: Matching groups with display name, address and resource name.
    """
    logger.info(f"[search_groups] Invoked. Email: '{user_google_email}' Query: '{query}'")

    if page_size < 1:
        raise UserInputError("page_size must be >= 1")
    page_size = min(page_size, 500)

    params: Dict[str, Any] = {
        "query": _customer_query(customer_id),
        "view": GROUP_VIEW_FULL,
        "pageSize": page_size,
    }
    if page_token:
        params["pageToken"] = page_token

    result = await asyncio.to_thread(service.groups().search(**params).execute)
    groups: List[Dict[str, Any]] = result.get("groups", [])

    if query:
        needle = query.lower()
        groups = [
            g
            for g in groups
            if needle in (g.get("displayName") or "").lower()
            or needle in g.get("groupKey", {}).get("id", "").lower()
        ]

    if not groups:
        return f"No groups found for {user_google_email}."

    response = f"Groups ({len(groups)}):\n\n" + "\n".join(_format_group(g) for g in groups)
    next_page_token = result.get("nextPageToken")
    if next_page_token:
        response += f"\n\nNext page token: {next_page_token}"
    return response


@server.tool()
@require_google_service("cloudidentity", "groups_read")
@handle_http_errors("get_group", service_type="cloudidentity")
async def get_group(
    service: Resource,
    user_google_email: str,
    group_email: str,
) -> str:
    """
    Get one Google Group by its email address.

    Args:
        user_google_email (str): The user's Google email address. Required.
        group_email (str): The group's address, e.g. "team@example.com".

    Returns:
        str: The group's display name, address, resource name and description.
    """
    logger.info(f"[get_group] Invoked. Group: '{group_email}'")

    name = await _resolve_group_name(service, group_email)
    group = await asyncio.to_thread(service.groups().get(name=name).execute)
    return _format_group(group)


@server.tool()
@require_google_service("cloudidentity", "groups_read")
@handle_http_errors("list_group_members", service_type="cloudidentity")
async def list_group_members(
    service: Resource,
    user_google_email: str,
    group_email: str,
    page_size: int = 200,
    page_token: Optional[str] = None,
) -> str:
    """
    List the direct members of a Google Group, with each member's roles.

    Roles are OWNER, MANAGER and MEMBER. A member holding MANAGER or OWNER can
    change the membership; MEMBER cannot.

    Args:
        user_google_email (str): The user's Google email address. Required.
        group_email (str): The group's address.
        page_size (int): Maximum members to return per page (default 200, max 500).
        page_token (Optional[str]): Token for pagination.

    Returns:
        str: Members with their roles.
    """
    logger.info(f"[list_group_members] Invoked. Group: '{group_email}'")

    if page_size < 1:
        raise UserInputError("page_size must be >= 1")
    page_size = min(page_size, 500)

    name = await _resolve_group_name(service, group_email)
    params: Dict[str, Any] = {"parent": name, "pageSize": page_size, "view": GROUP_VIEW_FULL}
    if page_token:
        params["pageToken"] = page_token

    result = await asyncio.to_thread(service.groups().memberships().list(**params).execute)
    members = result.get("memberships", [])

    if not members:
        return f"{group_email} has no members."

    response = f"Members of {group_email} ({len(members)}):\n\n" + "\n".join(
        _format_membership(m) for m in members
    )
    next_page_token = result.get("nextPageToken")
    if next_page_token:
        response += f"\n\nNext page token: {next_page_token}"
    return response


@server.tool()
@require_google_service("cloudidentity", "groups_read")
@handle_http_errors("list_member_groups", service_type="cloudidentity")
async def list_member_groups(
    service: Resource,
    user_google_email: str,
    member_email: str,
) -> str:
    """
    List every group a person belongs to, including through nested groups.

    This is the membership an identity provider replicates and an application
    sees in the token, so it answers what a person can reach — not merely which
    groups name them directly.

    Args:
        user_google_email (str): The user's Google email address. Required.
        member_email (str): The person whose memberships to list.

    Returns:
        str: The groups the person belongs to, directly or transitively.
    """
    logger.info(f"[list_member_groups] Invoked. Member: '{member_email}'")

    result = await asyncio.to_thread(
        service.groups()
        .memberships()
        .searchTransitiveGroups(
            parent="groups/-",
            query=f"member_key_id == '{member_email}' && '{DISCUSSION_FORUM_LABEL}' in labels",
        )
        .execute
    )
    groups = result.get("memberships", [])

    if not groups:
        return f"{member_email} belongs to no groups."

    lines = []
    for g in groups:
        display = g.get("displayName") or "(no display name)"
        addr = g.get("groupKey", {}).get("id", "(no address)")
        relation = g.get("relationType", "")
        lines.append(f"- {display}  <{addr}>" + (f"  [{relation}]" if relation else ""))

    return f"Groups for {member_email} ({len(groups)}):\n\n" + "\n".join(lines)


@server.tool()
@require_google_service("cloudidentity", "groups_write")
@handle_http_errors("manage_group_member", service_type="cloudidentity")
async def manage_group_member(
    service: Resource,
    user_google_email: str,
    group_email: str,
    member_email: str,
    action: str = "add",
    role: str = "MEMBER",
) -> str:
    """
    Add or remove one member of a Google Group.

    The caller must hold OWNER or MANAGER on the group; MEMBER is not enough.

    Args:
        user_google_email (str): The user's Google email address. Required.
        group_email (str): The group's address.
        member_email (str): The person to add or remove.
        action (str): "add" or "remove".
        role (str): Role to grant when adding: MEMBER, MANAGER or OWNER.

    Returns:
        str: Confirmation of the change.
    """
    logger.info(f"[manage_group_member] {action} {member_email} on {group_email}")

    if action not in ("add", "remove"):
        raise UserInputError("action must be 'add' or 'remove'")
    if role not in ("MEMBER", "MANAGER", "OWNER"):
        raise UserInputError("role must be MEMBER, MANAGER or OWNER")

    name = await _resolve_group_name(service, group_email)

    if action == "add":
        body = {"preferredMemberKey": {"id": member_email}, "roles": [{"name": role}]}
        await asyncio.to_thread(
            service.groups().memberships().create(parent=name, body=body).execute
        )
        return f"Added {member_email} to {group_email} as {role}."

    lookup = await asyncio.to_thread(
        service.groups()
        .memberships()
        .lookup(parent=name, memberKey_id=member_email)
        .execute
    )
    membership_name = lookup.get("name")
    if not membership_name:
        raise UserInputError(f"{member_email} is not a member of {group_email}.")

    await asyncio.to_thread(
        service.groups().memberships().delete(name=membership_name).execute
    )
    return f"Removed {member_email} from {group_email}."
