# Shared Drive lifecycle management

## Recommendation

Add Google Drive MCP tools that manage the Shared Drive container lifecycle, not
just folders inside My Drive or inside an existing Shared Drive.

Current observed gap:

- `create_drive_folder` can create folders, including inside an existing Shared
  Drive.
- File and folder tools can operate within a Shared Drive when given Shared Drive
  IDs and `supportsAllDrives=True` where required.
- No existing Drive tool manages the Shared Drive container itself.

A normal My Drive folder is not equivalent to a Shared Drive. Repo artifacts that
are too large for GitHub should live in an actual Google Shared Drive so
ownership, access requests, membership, and long-term discoverability are
organization-managed.

## Implemented lifecycle surface

The Drive API exposes Shared Drive containers through `v3.drives`. The MCP layer
should expose the smallest complete lifecycle surface:

```text
list_shared_drives
get_shared_drive
create_shared_drive
update_shared_drive
hide_shared_drive
unhide_shared_drive
delete_shared_drive
```

### `list_shared_drives`

Lists Shared Drives visible to the authenticated user, with optional Drive API
query, pagination, and domain-admin access flag.

Suggested input:

```json
{
  "user_google_email": "steve.antonakakis@moodmedia.com",
  "page_size": 100,
  "page_token": "optional-next-token",
  "query": "name contains 'Repo'",
  "use_domain_admin_access": false
}
```

### `get_shared_drive`

Gets Shared Drive metadata by ID.

```json
{
  "user_google_email": "steve.antonakakis@moodmedia.com",
  "drive_id": "shared-drive-id",
  "use_domain_admin_access": false
}
```

### `create_shared_drive`

Creates a Shared Drive container with `drives.create`.

```json
{
  "user_google_email": "steve.antonakakis@moodmedia.com",
  "drive_name": "MM GH Repo Large Items",
  "request_id": "optional-idempotency-uuid"
}
```

Behavior:

- Calls Google Drive API `drives.create`.
- Uses a UUID `requestId` for idempotency when the caller does not provide one.
- Returns Shared Drive metadata, including ID, name, created/hidden state,
  capabilities, restrictions, and the top-level Drive folder link when returned.
- Does not accept restrictions at creation time. Google Drive requires creating
  the Shared Drive first, then updating restrictions with `drives.update`.
- Fails through the existing Google API error path when the authenticated user
  cannot create Shared Drives.

API shape:

```text
POST https://www.googleapis.com/drive/v3/drives?requestId=<uuid>
Body: { "name": "MM GH Repo Large Items" }
```

### `update_shared_drive`

Updates Shared Drive metadata and restrictions with `drives.update`.

```json
{
  "user_google_email": "steve.antonakakis@moodmedia.com",
  "drive_id": "shared-drive-id",
  "drive_name": "New Shared Drive Name",
  "color_rgb": "#3367d6",
  "theme_id": "optional-theme-id",
  "restrictions": {
    "domainUsersOnly": true,
    "driveMembersOnly": true
  },
  "use_domain_admin_access": false
}
```

### `hide_shared_drive` / `unhide_shared_drive`

Hides or restores a Shared Drive in the authenticated user's default Drive view.
This is user-visible lifecycle state, not deletion.

```json
{
  "user_google_email": "steve.antonakakis@moodmedia.com",
  "drive_id": "shared-drive-id"
}
```

### `delete_shared_drive`

Permanently deletes a Shared Drive through `drives.delete`.

```json
{
  "user_google_email": "steve.antonakakis@moodmedia.com",
  "drive_id": "shared-drive-id",
  "use_domain_admin_access": false,
  "allow_item_deletion": false
}
```

Permission and behavior constraints:

- Google requires the caller to be an organizer for normal deletion.
- The Shared Drive cannot contain untrashed items unless Google accepts
  `allowItemDeletion` with domain-admin access.
- The tool should expose Google Drive's real behavior and errors; it should not
  fake cleanup, silently trash contents, or hide permission failures.

## OAuth scope

Lifecycle-mutating tools require full Drive scope:

```text
https://www.googleapis.com/auth/drive
```

Read-only list/get tools can use Drive readonly scope through the existing Drive
read path.

## Immediate target use case

```text
MM GH Repo Large Items/
└── MoodHyperauto/
    └── mm-tableau-services/
        └── tokenized-current/
```

The top-level `MM GH Repo Large Items` item should be a Shared Drive container.
The nested project path should be folders inside that Shared Drive.
