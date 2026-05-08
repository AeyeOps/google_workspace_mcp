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
