"""
Google Chat MCP Tools

This module provides MCP tools for interacting with Google Chat API.
"""

import base64
import logging
import asyncio
import ssl
from typing import Dict, List, Optional

import httpx
from googleapiclient.errors import HttpError

# Auth & server utilities
from auth.service_decorator import require_google_service, require_multiple_services
from core.server import server
from core.utils import TransientNetworkError, handle_http_errors

logger = logging.getLogger(__name__)

# In-memory cache for user ID → display name (bounded to avoid unbounded growth)
_SENDER_CACHE_MAX_SIZE = 256
_sender_name_cache: Dict[str, str] = {}
_SEARCH_MESSAGES_MAX_CONCURRENT_SPACE_FETCHES = 1
_SEARCH_MESSAGES_SSL_RETRIES = 3
_SEARCH_MESSAGES_RETRY_BASE_DELAY_SECONDS = 1


def _cache_sender(user_id: str, name: str) -> None:
    """Store a resolved sender name, evicting oldest entries if cache is full."""
    if len(_sender_name_cache) >= _SENDER_CACHE_MAX_SIZE:
        to_remove = list(_sender_name_cache.keys())[: _SENDER_CACHE_MAX_SIZE // 2]
        for k in to_remove:
            del _sender_name_cache[k]
    _sender_name_cache[user_id] = name


async def _resolve_sender(people_service, sender_obj: dict) -> str:
    """Resolve a Chat message sender to a display name.

    Fast path: use displayName if the API already provided it.
    Slow path: look up the user via the People API directory and cache the result.
    """
    # Fast path — Chat API sometimes provides displayName directly
    display_name = sender_obj.get("displayName")
    if display_name:
        return display_name

    user_id = sender_obj.get("name", "")  # e.g. "users/123456789"
    if not user_id:
        return "Unknown Sender"

    # Check cache
    if user_id in _sender_name_cache:
        return _sender_name_cache[user_id]

    # Try People API directory lookup
    # Chat API uses "users/ID" but People API expects "people/ID"
    people_resource = user_id.replace("users/", "people/", 1)
    if people_service:
        try:
            person = await asyncio.to_thread(
                people_service.people()
                .get(resourceName=people_resource, personFields="names,emailAddresses")
                .execute
            )
            names = person.get("names", [])
            if names:
                resolved = names[0].get("displayName", user_id)
                _cache_sender(user_id, resolved)
                return resolved
            # Fall back to email if no name
            emails = person.get("emailAddresses", [])
            if emails:
                resolved = emails[0].get("value", user_id)
                _cache_sender(user_id, resolved)
                return resolved
        except HttpError as e:
            logger.debug(f"People API lookup failed for {user_id}: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error resolving {user_id}: {e}")

    # Final fallback
    _cache_sender(user_id, user_id)
    return user_id


async def _execute_chat_request(
    request_factory,
    *,
    request_label: str,
    retries: int = 1,
    semaphore: Optional[asyncio.Semaphore] = None,
):
    """Execute a Chat API request in a worker thread with optional SSL retries."""
    for attempt in range(retries):
        try:
            if semaphore is None:
                return await asyncio.to_thread(lambda: request_factory().execute())
            async with semaphore:
                return await asyncio.to_thread(lambda: request_factory().execute())
        except ssl.SSLError as e:
            if attempt == retries - 1:
                raise
            delay = _SEARCH_MESSAGES_RETRY_BASE_DELAY_SECONDS * (2**attempt)
            logger.warning(
                "[search_messages] SSL error during %s on attempt %s/%s: %s. Retrying in %s seconds.",
                request_label,
                attempt + 1,
                retries,
                e,
                delay,
            )
            await asyncio.sleep(delay)


def _extract_rich_links(msg: dict) -> List[str]:
    """Extract URLs from RICH_LINK annotations (smart chips).

    When a user pastes a Google Workspace URL in Chat and it renders as a
    smart chip, the URL is NOT in the text field — it's only available in
    the annotations array as a RICH_LINK with richLinkMetadata.uri.
    """
    text = msg.get("text", "")
    urls = []
    for ann in msg.get("annotations", []):
        if ann.get("type") == "RICH_LINK":
            uri = ann.get("richLinkMetadata", {}).get("uri", "")
            if uri and uri not in text:
                urls.append(uri)
    return urls


@server.tool()
@require_google_service("chat", "chat_spaces_readonly")
@handle_http_errors("list_spaces", service_type="chat")
async def list_spaces(
    service,
    user_google_email: str,
    page_size: int = 100,
    space_type: str = "all",  # "all", "room", "dm"
) -> str:
    """
    Lists Google Chat spaces (rooms and direct messages) accessible to the user.

    Returns:
        str: A formatted list of Google Chat spaces accessible to the user.
    """
    logger.info(f"[list_spaces] Email={user_google_email}, Type={space_type}")

    # Build filter based on space_type
    filter_param = None
    if space_type == "room":
        filter_param = "spaceType = SPACE"
    elif space_type == "dm":
        filter_param = "spaceType = DIRECT_MESSAGE"

    request_params = {"pageSize": page_size}
    if filter_param:
        request_params["filter"] = filter_param

    response = await asyncio.to_thread(service.spaces().list(**request_params).execute)

    spaces = response.get("spaces", [])
    if not spaces:
        return f"No Chat spaces found for type '{space_type}'."

    output = [f"Found {len(spaces)} Chat spaces (type: {space_type}):"]
    for space in spaces:
        space_name = space.get("displayName", "Unnamed Space")
        space_id = space.get("name", "")
        space_type_actual = space.get("spaceType", "UNKNOWN")
        output.append(f"- {space_name} (ID: {space_id}, Type: {space_type_actual})")

    return "\n".join(output)


@server.tool()
@require_multiple_services(
    [
        {"service_type": "chat", "scopes": "chat_read", "param_name": "chat_service"},
        {
            "service_type": "people",
            "scopes": "contacts_read",
            "param_name": "people_service",
        },
    ]
)
@handle_http_errors("get_messages", service_type="chat")
async def get_messages(
    chat_service,
    people_service,
    user_google_email: str,
    space_id: str,
    page_size: int = 50,
    order_by: str = "createTime desc",
    message_filter: Optional[str] = None,
) -> str:
    """
    Retrieves messages from a Google Chat space.

    Args:
        message_filter: Optional filter string using the Chat API filter syntax.
                        Supports createTime and thread.name.
                        Examples:
                          'createTime > "2026-03-18T00:00:00-03:00"'
                          'createTime > "2026-03-18T00:00:00-03:00" AND createTime < "2026-03-19T00:00:00-03:00"'
                          'thread.name = spaces/X/threads/Y'

    Returns:
        str: Formatted messages from the specified space.
    """
    logger.info(f"[get_messages] Space ID: '{space_id}' for user '{user_google_email}'")

    # Get space info first
    space_info = await asyncio.to_thread(
        chat_service.spaces().get(name=space_id).execute
    )
    space_name = space_info.get("displayName", "Unknown Space")

    # Get messages
    list_params = {"parent": space_id, "pageSize": page_size, "orderBy": order_by}
    if message_filter is not None:
        list_params["filter"] = message_filter
    response = await asyncio.to_thread(
        chat_service.spaces().messages().list(**list_params).execute
    )

    messages = response.get("messages", [])
    if not messages:
        return f"No messages found in space '{space_name}' (ID: {space_id})."

    # Pre-resolve unique senders in parallel
    sender_lookup = {}
    for msg in messages:
        s = msg.get("sender", {})
        key = s.get("name", "")
        if key and key not in sender_lookup:
            sender_lookup[key] = s
    resolved_names = await asyncio.gather(
        *[_resolve_sender(people_service, s) for s in sender_lookup.values()]
    )
    sender_map = dict(zip(sender_lookup.keys(), resolved_names))

    output = [f"Messages from '{space_name}' (ID: {space_id}):\n"]
    for msg in messages:
        sender_obj = msg.get("sender", {})
        sender_key = sender_obj.get("name", "")
        sender = sender_map.get(sender_key) or await _resolve_sender(
            people_service, sender_obj
        )
        create_time = msg.get("createTime", "Unknown Time")
        text_content = msg.get("text", "No text content")
        msg_name = msg.get("name", "")

        output.append(f"[{create_time}] {sender}:")
        output.append(f"  {text_content}")
        rich_links = _extract_rich_links(msg)
        for url in rich_links:
            output.append(f"  [linked: {url}]")
        # Show attachments
        attachments = msg.get("attachment", [])
        for idx, att in enumerate(attachments):
            att_name = att.get("contentName", "unnamed")
            att_type = att.get("contentType", "unknown type")
            att_resource = att.get("name", "")
            output.append(f"  [attachment {idx}: {att_name} ({att_type})]")
            if att_resource:
                output.append(
                    f"  Use download_chat_attachment(message_id='{msg_name}', attachment_index={idx}) to download"
                )
        # Show thread info if this is a threaded reply
        thread = msg.get("thread", {})
        if msg.get("threadReply") and thread.get("name"):
            output.append(f"  [thread: {thread['name']}]")
        # Show emoji reactions
        reactions = msg.get("emojiReactionSummaries", [])
        if reactions:
            parts = []
            for r in reactions:
                emoji = r.get("emoji", {})
                symbol = emoji.get("unicode", "")
                if not symbol:
                    ce = emoji.get("customEmoji", {})
                    symbol = f":{ce.get('uid', '?')}:"
                count = r.get("reactionCount", 0)
                parts.append(f"{symbol}x{count}")
            output.append(f"  [reactions: {', '.join(parts)}]")
        output.append(f"  (Message ID: {msg_name})\n")

    return "\n".join(output)


@server.tool()
@require_google_service("chat", "chat_write")
@handle_http_errors("send_message", service_type="chat")
async def send_message(
    service,
    user_google_email: str,
    space_id: str,
    message_text: str,
    thread_key: Optional[str] = None,
    thread_name: Optional[str] = None,
) -> str:
    """
    Sends a message to a Google Chat space.

    Args:
        thread_name: Reply in an existing thread by its resource name (e.g. spaces/X/threads/Y).
        thread_key: Reply in a thread by app-defined key (creates thread if not found).

    Returns:
        str: Confirmation message with sent message details.
    """
    logger.info(f"[send_message] Email: '{user_google_email}', Space: '{space_id}'")

    message_body = {"text": message_text}

    request_params = {"parent": space_id, "body": message_body}

    # Thread reply support
    if thread_name:
        message_body["thread"] = {"name": thread_name}
        request_params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    elif thread_key:
        message_body["thread"] = {"threadKey": thread_key}
        request_params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

    message = await asyncio.to_thread(
        service.spaces().messages().create(**request_params).execute
    )

    message_name = message.get("name", "")
    create_time = message.get("createTime", "")

    msg = f"Message sent to space '{space_id}' by {user_google_email}. Message ID: {message_name}, Time: {create_time}"
    logger.info(
        f"Successfully sent message to space '{space_id}' by {user_google_email}"
    )
    return msg


@server.tool()
@require_multiple_services(
    [
        {"service_type": "chat", "scopes": "chat_read", "param_name": "chat_service"},
        {
            "service_type": "people",
            "scopes": "contacts_read",
            "param_name": "people_service",
        },
    ]
)
@handle_http_errors("search_messages", is_read_only=True, service_type="chat")
async def search_messages(
    chat_service,
    people_service,
    user_google_email: str,
    query: Optional[str] = None,
    space_id: Optional[str] = None,
    page_size: int = 25,
    time_filter: Optional[str] = None,
    max_spaces: int = 10,
) -> str:
    """
    Searches for messages in Google Chat spaces by text content and/or time range.

    Args:
        query: Optional text to search for. If omitted, only time_filter is applied.
        space_id: Optional space to restrict the search to.
        page_size: Maximum number of messages to return per space.
        time_filter: Optional filter using Chat API createTime syntax.
                     Examples:
                       'createTime > "2026-03-18T00:00:00-03:00"'
                       'createTime > "2026-03-18T00:00:00-03:00" AND createTime < "2026-03-19T00:00:00-03:00"'
        max_spaces: Maximum number of spaces to search when space_id is not provided (default 10).

    Returns:
        str: A formatted list of messages matching the search criteria.
    """
    logger.info(
        f"[search_messages] Email={user_google_email}, Query='{query}', TimeFilter='{time_filter}'"
    )

    # Google Chat messages.list supports time/thread filters, but not full-text
    # search. Apply only supported API filters, then filter message text below.
    filter_parts = []
    if time_filter:
        filter_parts.append(time_filter)
    filter_str = " AND ".join(filter_parts) if filter_parts else None

    search_terms = []
    if query:
        search_terms.append(f'text "{query}"')
    if time_filter:
        search_terms.append(time_filter)
    search_desc = " and ".join(search_terms) if search_terms else "all messages"

    # If specific space provided, search within that space
    if space_id:
        list_params = {"parent": space_id, "pageSize": page_size}
        if filter_str:
            list_params["filter"] = filter_str
        response = await _execute_chat_request(
            lambda: chat_service.spaces().messages().list(**list_params),
            request_label=f"fetching messages for {space_id}",
            retries=_SEARCH_MESSAGES_SSL_RETRIES,
        )
        messages = response.get("messages", [])
        context = f"space '{space_id}'"
    else:
        # Search across all accessible spaces
        spaces_response = await _execute_chat_request(
            lambda: chat_service.spaces().list(pageSize=100),
            request_label="listing accessible spaces",
            retries=_SEARCH_MESSAGES_SSL_RETRIES,
        )
        spaces = spaces_response.get("spaces", [])
        spaces_to_search = spaces[:max_spaces]
        fetch_semaphore = asyncio.Semaphore(
            _SEARCH_MESSAGES_MAX_CONCURRENT_SPACE_FETCHES
        )

        async def fetch_space_messages(space: dict) -> tuple[List[dict], bool]:
            try:
                list_params = {"parent": space.get("name"), "pageSize": page_size}
                if filter_str:
                    list_params["filter"] = filter_str
                response = await _execute_chat_request(
                    lambda: chat_service.spaces().messages().list(**list_params),
                    request_label=f"fetching messages for {space.get('name')}",
                    retries=_SEARCH_MESSAGES_SSL_RETRIES,
                    semaphore=fetch_semaphore,
                )
                msgs = response.get("messages", [])
                display = space.get("displayName", "Unknown")
                for msg in msgs:
                    msg["_space_name"] = display
                return msgs, False
            except HttpError as e:
                logger.debug(
                    "Skipping space %s during search: %s", space.get("name"), e
                )
                return [], False
            except ssl.SSLError as e:
                logger.warning(
                    "Skipping space %s during search after repeated SSL failures: %s",
                    space.get("name"),
                    e,
                )
                return [], True

        results = await asyncio.gather(
            *(fetch_space_messages(space) for space in spaces_to_search)
        )
        transient_failures = 0
        messages = []
        for batch, had_transient_failure in results:
            messages.extend(batch)
            transient_failures += int(had_transient_failure)
        if spaces_to_search and transient_failures == len(spaces_to_search):
            raise TransientNetworkError(
                "A transient SSL error occurred in 'search_messages' while searching Chat spaces. "
                "Please try again shortly."
            )
        context = "all accessible spaces"

    # Client-side text filtering (text: operator is not supported by the API)
    if query:
        query_lower = query.lower()
        messages = [m for m in messages if query_lower in (m.get("text") or "").lower()]

    if not messages:
        suffix = (
            f" Skipped {transient_failures} spaces due to repeated SSL failures."
            if "transient_failures" in locals() and transient_failures
            else ""
        )
        return f"No messages found matching '{search_desc}' in {context}.{suffix}"

    # Resolve senders sequentially. The underlying googleapiclient/httplib2
    # service objects are not safe to fan out heavily and can trigger SSL churn.
    sender_lookup = {}
    for msg in messages:
        s = msg.get("sender", {})
        key = s.get("name", "")
        if key and key not in sender_lookup:
            sender_lookup[key] = s
    sender_map = {}
    for key, sender_obj in sender_lookup.items():
        sender_map[key] = await _resolve_sender(people_service, sender_obj)

    output = [f"Found {len(messages)} messages matching '{search_desc}' in {context}:"]
    for msg in messages:
        sender_obj = msg.get("sender", {})
        sender_key = sender_obj.get("name", "")
        sender = sender_map.get(sender_key) or await _resolve_sender(
            people_service, sender_obj
        )
        create_time = msg.get("createTime", "Unknown Time")
        text_content = msg.get("text", "No text content")
        space_name = msg.get("_space_name", "Unknown Space")

        # Truncate long messages
        if len(text_content) > 100:
            text_content = text_content[:100] + "..."

        rich_links = _extract_rich_links(msg)
        links_suffix = "".join(f" [linked: {url}]" for url in rich_links)
        attachments = msg.get("attachment", [])
        att_suffix = "".join(
            f" [attachment: {a.get('contentName', 'unnamed')} ({a.get('contentType', 'unknown type')})]"
            for a in attachments
        )
        output.append(
            f"- [{create_time}] {sender} in '{space_name}': {text_content}{links_suffix}{att_suffix}"
        )

    return "\n".join(output)


@server.tool()
@require_google_service("chat", "chat_write")
@handle_http_errors("create_reaction", service_type="chat")
async def create_reaction(
    service,
    user_google_email: str,
    message_id: str,
    emoji_unicode: str,
) -> str:
    """
    Adds an emoji reaction to a Google Chat message.

    Args:
        message_id: The message resource name (e.g. spaces/X/messages/Y).
        emoji_unicode: The emoji character to react with (e.g. 👍).

    Returns:
        str: Confirmation message.
    """
    logger.info(f"[create_reaction] Message: '{message_id}', Emoji: '{emoji_unicode}'")

    reaction = await asyncio.to_thread(
        service.spaces()
        .messages()
        .reactions()
        .create(
            parent=message_id,
            body={"emoji": {"unicode": emoji_unicode}},
        )
        .execute
    )

    reaction_name = reaction.get("name", "")
    return f"Reacted with {emoji_unicode} on message {message_id}. Reaction ID: {reaction_name}"


@server.tool()
@handle_http_errors("download_chat_attachment", is_read_only=True, service_type="chat")
@require_google_service("chat", "chat_read")
async def download_chat_attachment(
    service,
    user_google_email: str,
    message_id: str,
    attachment_index: int = 0,
) -> str:
    """
    Downloads an attachment from a Google Chat message and saves it to local disk.

    In stdio mode, returns the local file path for direct access.
    In HTTP mode, returns a temporary download URL (valid for 1 hour).

    Args:
        message_id: The message resource name (e.g. spaces/X/messages/Y).
        attachment_index: Zero-based index of the attachment to download (default 0).

    Returns:
        str: Attachment metadata with either a local file path or download URL.
    """
    logger.info(
        f"[download_chat_attachment] Message: '{message_id}', Index: {attachment_index}"
    )

    # Fetch the message to get attachment metadata
    msg = await asyncio.to_thread(
        service.spaces().messages().get(name=message_id).execute
    )

    attachments = msg.get("attachment", [])
    if not attachments:
        return f"No attachments found on message {message_id}."

    if attachment_index < 0 or attachment_index >= len(attachments):
        return (
            f"Invalid attachment_index {attachment_index}. "
            f"Message has {len(attachments)} attachment(s) (0-{len(attachments) - 1})."
        )

    att = attachments[attachment_index]
    filename = att.get("contentName", "attachment")
    content_type = att.get("contentType", "application/octet-stream")
    source = att.get("source", "")

    # The media endpoint needs attachmentDataRef.resourceName (e.g.
    # "spaces/S/attachments/A"), NOT the attachment name which includes
    # the /messages/ segment and causes 400 errors.
    media_resource = att.get("attachmentDataRef", {}).get("resourceName", "")
    att_name = att.get("name", "")

    logger.info(
        f"[download_chat_attachment] Downloading '{filename}' ({content_type}), "
        f"source={source}, mediaResource={media_resource}, name={att_name}"
    )

    # Download the attachment binary data via the Chat API media endpoint.
    # We use httpx with the Bearer token directly because MediaIoBaseDownload
    # and AuthorizedHttp fail in OAuth 2.1 (no refresh_token). The attachment's
    # downloadUri points to chat.google.com which requires browser cookies.
    if not media_resource and not att_name:
        return f"No resource name available for attachment '{filename}'."

    # Prefer attachmentDataRef.resourceName for the media endpoint
    resource_name = media_resource or att_name
    download_url = f"https://chat.googleapis.com/v1/media/{resource_name}?alt=media"

    try:
        access_token = service._http.credentials.token
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(
                download_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                body = resp.text[:500]
                return (
                    f"Failed to download attachment '{filename}': "
                    f"HTTP {resp.status_code} from {download_url}\n{body}"
                )
            file_bytes = resp.content
    except Exception as e:
        return f"Failed to download attachment '{filename}': {e}"

    size_bytes = len(file_bytes)
    size_kb = size_bytes / 1024

    # Check if we're in stateless mode (can't save files)
    from auth.oauth_config import is_stateless_mode

    if is_stateless_mode():
        b64_preview = base64.urlsafe_b64encode(file_bytes).decode("utf-8")[:100]
        return "\n".join(
            [
                f"Attachment downloaded: {filename} ({content_type})",
                f"Size: {size_kb:.1f} KB ({size_bytes} bytes)",
                "",
                "Stateless mode: File storage disabled.",
                f"Base64 preview: {b64_preview}...",
            ]
        )

    # Save to local disk
    from core.attachment_storage import get_attachment_storage, get_attachment_url
    from core.config import get_transport_mode

    storage = get_attachment_storage()
    b64_data = base64.urlsafe_b64encode(file_bytes).decode("utf-8")
    result = storage.save_attachment(
        base64_data=b64_data, filename=filename, mime_type=content_type
    )

    result_lines = [
        f"Attachment downloaded: {filename}",
        f"Type: {content_type}",
        f"Size: {size_kb:.1f} KB ({size_bytes} bytes)",
    ]

    if get_transport_mode() == "stdio":
        result_lines.append(f"\nSaved to: {result.path}")
        result_lines.append(
            "\nThe file has been saved to disk and can be accessed directly via the file path."
        )
    else:
        download_url = get_attachment_url(result.file_id)
        result_lines.append(f"\nDownload URL: {download_url}")
        result_lines.append("\nThe file will expire after 1 hour.")

    logger.info(
        f"[download_chat_attachment] Saved {size_kb:.1f} KB attachment to {result.path}"
    )
    return "\n".join(result_lines)


@server.tool()
@require_google_service("chat", "chat_spaces_readonly")
@handle_http_errors("get_space", is_read_only=True, service_type="chat")
async def get_space(
    service,
    user_google_email: str,
    space_id: str,
) -> str:
    """
    Retrieves metadata for a single Google Chat space.

    Args:
        space_id: The space resource name (e.g. spaces/AAAA...). Caller must be
                  a member of the space; spaces.get on a non-member discoverable
                  space returns HTTP 403.

    Returns:
        str: Formatted metadata including display name, type, history state,
             member count, and description when available.
    """
    logger.info(f"[get_space] Space ID: '{space_id}' for user '{user_google_email}'")

    space = await asyncio.to_thread(service.spaces().get(name=space_id).execute)

    lines = [
        f"Space: {space.get('displayName', '(no display name)')}",
        f"  ID: {space.get('name', '')}",
        f"  Type: {space.get('spaceType', 'UNKNOWN')}",
    ]

    space_history_state = space.get("spaceHistoryState")
    if space_history_state:
        lines.append(f"  History: {space_history_state}")

    create_time = space.get("createTime")
    if create_time:
        lines.append(f"  Created: {create_time}")

    member_count = space.get("membershipCount") or {}
    joined_humans = member_count.get("joinedDirectHumanUserCount")
    joined_groups = member_count.get("joinedGroupCount")
    if joined_humans is not None or joined_groups is not None:
        parts = []
        if joined_humans is not None:
            parts.append(f"{joined_humans} humans")
        if joined_groups is not None:
            parts.append(f"{joined_groups} groups")
        lines.append(f"  Members: {', '.join(parts)}")

    if space.get("externalUserAllowed") is not None:
        lines.append(f"  External users allowed: {space['externalUserAllowed']}")

    space_details = space.get("spaceDetails") or {}
    description = space_details.get("description")
    if description:
        lines.append(f"  Description: {description}")
    guidelines = space_details.get("guidelines")
    if guidelines:
        lines.append(f"  Guidelines: {guidelines}")

    import_mode = space.get("importMode")
    if import_mode:
        lines.append(f"  Import mode: {import_mode}")

    space_uri = space.get("spaceUri")
    if space_uri:
        lines.append(f"  URL: {space_uri}")

    return "\n".join(lines)


@server.tool()
@require_google_service("chat", "chat_spaces_readonly")
@handle_http_errors("find_direct_message", is_read_only=True, service_type="chat")
async def find_direct_message(
    service,
    user_google_email: str,
    target_user: str,
) -> str:
    """
    Resolves the direct-message space ID for a given user.

    Wraps spaces.findDirectMessage. Empirically the Chat API accepts the
    email form (users/<email>) only for the authenticated caller; to look up
    a DM with another user, supply their numeric user ID (users/<id>).

    Args:
        target_user: The other participant. Accepts any of:
                     - full resource name: "users/123456789"
                     - bare numeric ID:    "123456789"
                     - email (caller-self only): "me@example.com"

    Returns:
        str: The DM space resource name and basic metadata, or a 404
             message if no DM exists yet.
    """
    name = target_user if target_user.startswith("users/") else f"users/{target_user}"
    logger.info(
        f"[find_direct_message] Caller: '{user_google_email}', Target: '{name}'"
    )

    space = await asyncio.to_thread(
        service.spaces().findDirectMessage(name=name).execute
    )

    space_name = space.get("name", "")
    space_type = space.get("spaceType", "UNKNOWN")
    display_name = space.get("displayName", "")
    create_time = space.get("createTime", "")

    lines = [
        f"Direct message space for {name}:",
        f"  ID: {space_name}",
        f"  Type: {space_type}",
    ]
    if display_name:
        lines.append(f"  Display name: {display_name}")
    if create_time:
        lines.append(f"  Created: {create_time}")

    return "\n".join(lines)


@server.tool()
@require_google_service("chat", "chat_memberships_readonly")
@handle_http_errors("find_group_chats", is_read_only=True, service_type="chat")
async def find_group_chats(
    service,
    user_google_email: str,
    users: List[str],
) -> str:
    """
    Finds group-chat spaces whose membership is EXACTLY the caller plus the
    supplied users.

    Wraps spaces.findGroupChats. This is an exact-match lookup, not a fuzzy
    search: the resulting spaces contain precisely {caller} ∪ {users} and no
    others. Empty result means no such group chat exists.

    Args:
        users: Other participants to match. Each entry may be:
               - full resource name: "users/123456789"
               - bare numeric ID:    "123456789"
               Numeric IDs are required for third parties — email aliases
               work only for the caller's own user (per Chat API). Maximum
               49 entries (API limit).

    Returns:
        str: Formatted list of matching group-chat spaces, or an empty-result
             message if none match.
    """
    if len(users) > 49:
        raise ValueError(
            f"find_group_chats supports at most 49 users; got {len(users)}"
        )

    normalized = [u if u.startswith("users/") else f"users/{u}" for u in users]
    logger.info(
        f"[find_group_chats] Caller: '{user_google_email}', "
        f"Members: {normalized}"
    )

    resp = await asyncio.to_thread(
        service.spaces().findGroupChats(users=normalized, pageSize=30).execute
    )

    spaces = resp.get("spaces", [])
    if not spaces:
        return "No group-chat spaces match that exact membership."

    lines = [f"Found {len(spaces)} group-chat space(s):"]
    for s in spaces:
        name = s.get("name", "")
        display = s.get("displayName") or "(no display name)"
        space_type = s.get("spaceType", "UNKNOWN")
        created = s.get("createTime", "")
        lines.append(f"  - {display}")
        lines.append(f"      ID: {name}")
        lines.append(f"      Type: {space_type}")
        if created:
            lines.append(f"      Created: {created}")

    return "\n".join(lines)


@server.tool()
@require_google_service("chat", "chat_memberships_readonly")
@handle_http_errors("list_space_members", is_read_only=True, service_type="chat")
async def list_space_members(
    service,
    user_google_email: str,
    space_id: str,
    page_size: int = 100,
    filter: Optional[str] = None,
    show_invited: bool = False,
) -> str:
    """
    Lists memberships in a Google Chat space.

    Wraps spaces.members.list. Returns humans, bots, and (optionally)
    invited-but-unjoined members. Caller must be a member of the space, or
    the space must be discoverable to the caller, or 403 is returned.

    Args:
        space_id: The space resource name (e.g. spaces/AAAA...).
        page_size: Page size, 1-1000 (Chat API default 100).
        filter: Optional server-side filter, e.g. "member.type = 'HUMAN'" or
                "role = 'ROLE_MEMBER'". See Chat API docs for grammar.
        show_invited: Include memberships in INVITED state (default False).

    Returns:
        str: Formatted membership list with name, type, role, state, and
             create time for each entry.
    """
    logger.info(
        f"[list_space_members] Space: '{space_id}' for user '{user_google_email}' "
        f"(page_size={page_size}, filter={filter!r}, show_invited={show_invited})"
    )

    kwargs = {"parent": space_id, "pageSize": page_size, "showInvited": show_invited}
    if filter is not None:
        kwargs["filter"] = filter

    resp = await asyncio.to_thread(
        service.spaces().members().list(**kwargs).execute
    )

    memberships = resp.get("memberships", [])
    if not memberships:
        return f"No memberships found in {space_id}."

    lines = [f"Memberships in {space_id} ({len(memberships)} shown):"]
    for m in memberships:
        member = m.get("member") or {}
        member_name = member.get("name", "")
        member_type = member.get("type", "UNKNOWN")
        role = m.get("role", "")
        state = m.get("state", "")
        created = m.get("createTime", "")
        lines.append(f"  - {member_name} ({member_type})")
        if role:
            lines.append(f"      Role: {role}")
        if state:
            lines.append(f"      State: {state}")
        if created:
            lines.append(f"      Joined: {created}")

    next_token = resp.get("nextPageToken")
    if next_token:
        lines.append(f"\n(More members available; nextPageToken={next_token})")

    return "\n".join(lines)


@server.tool()
@require_google_service("chat", "chat_memberships")
@handle_http_errors("join_space", is_read_only=False, service_type="chat")
async def join_space(
    service,
    user_google_email: str,
    space_id: str,
) -> str:
    """
    Self-joins the authenticated caller to a Google Chat space.

    Wraps spaces.members.create. Uses the email-alias form of the member
    name, which the Chat API accepts for self-join (no People API lookup
    required — verified empirically 2026-04-20).

    Args:
        space_id: The space resource name (e.g. spaces/AAAA...).

    Returns:
        str: Confirmation including the new membership resource name and
             role. Surfaces 403 if the space isn't discoverable to the
             caller, and 409 if caller is already a member.
    """
    body = {
        "member": {
            "name": f"users/{user_google_email}",
            "type": "HUMAN",
        },
    }
    logger.info(
        f"[join_space] Caller: '{user_google_email}' joining '{space_id}'"
    )

    membership = await asyncio.to_thread(
        service.spaces().members().create(parent=space_id, body=body).execute
    )

    name = membership.get("name", "")
    role = membership.get("role", "")
    state = membership.get("state", "")
    return (
        f"Joined {space_id}\n"
        f"  Membership: {name}\n"
        f"  Role: {role}\n"
        f"  State: {state}"
    )


@server.tool()
@require_google_service("chat", "chat_memberships")
@handle_http_errors("leave_space", is_read_only=False, service_type="chat")
async def leave_space(
    service,
    user_google_email: str,
    space_id: str,
) -> str:
    """
    Removes the authenticated caller from a Google Chat space.

    Wraps spaces.members.delete. Uses the email-alias form for the
    membership resource name, which the Chat API accepts for self-leave
    (verified empirically 2026-04-20).

    Args:
        space_id: The space resource name (e.g. spaces/AAAA...).

    Returns:
        str: Confirmation that the membership was removed.
    """
    membership_name = f"{space_id}/members/{user_google_email}"
    logger.info(
        f"[leave_space] Caller: '{user_google_email}' leaving '{space_id}'"
    )

    await asyncio.to_thread(
        service.spaces().members().delete(name=membership_name).execute
    )

    return f"Left {space_id} (removed membership {membership_name})"
