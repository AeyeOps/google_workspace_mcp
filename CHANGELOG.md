# Changelog

All notable changes to the AeyeOps fork of `google_workspace_mcp` are documented
here. The format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Shared Drive lifecycle tools** — adds `list_shared_drives`,
  `get_shared_drive`, `create_shared_drive`, `update_shared_drive`,
  `hide_shared_drive`, `unhide_shared_drive`, and `delete_shared_drive`
  for managing Shared Drive containers through Drive API v3 `drives.*`.
  Read-only list/get use `drive_read`; lifecycle mutations require full
  `drive` scope. The docs now distinguish Shared Drive containers from
  folders inside Shared Drives.
- **`create_drive_shortcut` tool** — creates a Drive shortcut
  (`application/vnd.google-apps.shortcut`) that points at an existing file or
  folder, in a chosen parent folder. Uses the existing `drive_file` scope.
  Registered in `drive.core` tier. Enables grouping "Shared with me" files
  into a user-owned folder without copying or moving originals. The MCP
  already dereferences shortcuts on read via `resolve_drive_item`; this
  closes the corresponding write-side gap.
- **Google Groups tools** — adds `search_groups`, `get_group`,
  `list_group_members`, `list_member_groups`, and `manage_group_member` on the
  Cloud Identity Groups API. Group membership is what an identity provider
  replicates and what an application reads from a token, so it answers "who can
  reach this?" — a question the People/Directory surface cannot address, since
  it exposes people rather than the groups gating them. Reads take
  `cloud-identity.groups.readonly`; only the membership write takes
  `cloud-identity.groups`. Callers pass a group address throughout and the tools
  resolve the server-assigned `groups/<id>` internally.

### Fixed
- **`search_groups` rejected its own default.** Cloud Identity does not accept
  the `my_customer` alias the Admin SDK takes, so every call with the default
  `customer_id` returned `400 Request contains an invalid argument`. The alias
  is now exchanged for the account's real `C…` id through the Admin SDK before
  it reaches the query.
- **Chat showed numeric ids instead of people.** `list_space_members` printed
  `users/<id>` verbatim, and `list_spaces` labelled every DM and group chat
  "Unnamed Space" because Chat sets `displayName` only on named spaces. Both now
  resolve identities, and an unnamed DM or group chat is labelled by its members.
- **Sender resolution never worked for colleagues.** `_resolve_sender` fell back
  to `people.get(people/<id>)`, which returns `200` with an empty person for
  anyone outside the caller's own contacts; the code read that empty result, fell
  through, and cached the raw id as the answer. Resolution now uses Admin SDK
  Directory `users.get`, and misses are no longer cached.
- **The People directory surface is unusable when a domain disables external
  directory sharing**, which `403`s `searchDirectoryPeople` and
  `listDirectoryPeople` for every caller in that domain. Chat identity therefore
  depends on `admin.directory.user.readonly` rather than `directory.readonly`.
  `search_directory_people` remains subject to the same domain setting.
- **Tools could load but never register.** `core/tool_tiers.yaml` is an
  allowlist: with `--tool-tier` set, a service imports and its tools are dropped
  unless listed there. The group tools are now registered across the tiers.

## [1.20.0] — 2026-04-20

### Added
- **Google Chat memberships API** — four new tool wrappers:
  - `find_group_chats(users)` — wraps `spaces.findGroupChats` (extended tier, read-only)
  - `list_space_members(space_id, ...)` — wraps `spaces.members.list` (extended tier, read-only)
  - `join_space(space_id)` — wraps `spaces.members.create` (complete tier, write)
  - `leave_space(space_id)` — wraps `spaces.members.delete` (complete tier, write)
- OAuth scope plumbing for `chat.memberships` and `chat.memberships.readonly`
  across `auth/scopes.py`, `auth/service_decorator.py`, and `auth/permissions.py`.
  The two scopes are registered as an independent hierarchy branch from
  `chat.spaces` (they do not cover each other).
- Local dev workflow: `Makefile` with fail-fast recipes (`help`, `install`,
  `test`, `lint`, `build-and-install`, `mcp-register`, `mcp-unregister`, `run`,
  `run-http`) and `scripts/make_mcp_register.py` for wiring the local build
  into Claude Code as `workspace-mm`.

### Changed
- Centralized Google service-client construction behind `build_google_service()`
  in `auth/google_auth.py`. All credential-authenticated `build()` call sites
  now go through this helper, which uses `static_discovery=False` so newly
  released API methods (e.g. `chat.spaces.findGroupChats`) are available
  without waiting for a `google-api-python-client` release with an updated
  bundled discovery doc. googleapiclient caches discovery in-memory, so the
  one-time HTTP fetch per `(service, version)` does not repeat across tool
  invocations.
