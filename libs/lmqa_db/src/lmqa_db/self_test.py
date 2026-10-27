"""Boot self-test and fail-closed RLS verification helpers.

Master System Design §5.4 & Gate G1.3.
"""

from __future__ import annotations


def assert_fail_closed_environment(ctx_org_id: str | None) -> bool:
    """Verify that an unconfigured context fails closed (rejects execution).

    Args:
        ctx_org_id: The active organization id string or None.

    Returns:
        True if an active, non-empty tenant context is set.

    Raises:
        PermissionError: If context is empty or missing (fail-closed rule).
    """
    if not ctx_org_id or not ctx_org_id.strip():
        msg = "Fail-closed invariant violation: No tenant context set for database operation."
        raise PermissionError(msg)
    return True


def check_table_rls_force_rule(*, table_rls_enabled: bool, table_rls_forced: bool) -> bool:
    """Verify that a table has both RLS enabled and FORCE RLS enabled.

    Per Gate G1.2: Every table must have FORCE RLS to prevent table-owner bypass.

    Args:
        table_rls_enabled: relrowsecurity from pg_class.
        table_rls_forced: relforcerowsecurity from pg_class.

    Returns:
        True if both flags are active.
    """
    return table_rls_enabled and table_rls_forced
