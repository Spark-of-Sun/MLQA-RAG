from __future__ import annotations

import pytest
from common.models import Action


@pytest.mark.asyncio
async def test_audit_search_requires_export_action(client, auth_header):
    headers = auth_header(action=Action.QUERY)
    response = await client.get("/v1/audit", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_search_with_export_role(client, auth_header):
    headers = auth_header(action=Action.EXPORT)
    response = await client.get("/v1/audit", headers=headers)
    assert response.status_code == 200
    assert response.json() == []
