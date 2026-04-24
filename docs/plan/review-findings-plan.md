# Review Findings Remediation Plan

Source: conversation context from `aeodlc-review-code` on the Chat space-management implementation.

## Status

Findings scope: COMPLETE
Spec scope: NOT EVALUATED

## Findings Tracker

| F-ID | Severity | Finding | Action | Status | Verification |
| --- | --- | --- | --- | --- | --- |
| F-001 | P1 | `list_space_members` did not emit membership resource names needed by `manage_space_member(update/remove)`. | Add `Membership: spaces/.../members/...` to each listed member row and cover it with a focused Chat tool test. | Completed | `uv run pytest tests/gchat/test_chat_tools.py` |
| F-002 | P2 | The plan expected `delete_space` to raise a local `UserInputError` under `chat:manage`, but the live MCP registry filters the tool out because `chat.delete` is outside the selected scope set. | Align docs/plan wording with actual registry behavior and add component coverage proving `chat:manage` filters `delete_space` while `chat:full` keeps it. | Completed | `uv run pytest tests/test_main_permissions_tier.py tests/test_permissions.py` |

## Milestones

1. Emit chainable membership identifiers from `list_space_members`.
2. Align permission-surface documentation with actual MCP tool filtering.
3. Add regression coverage for membership output and permission filtering.
4. Run focused and lightweight repo verification.

## Remaining Work

None for the reviewed findings.
