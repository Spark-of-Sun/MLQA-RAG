from __future__ import annotations

import pytest
from common.models import Action


@pytest.mark.asyncio
async def test_create_tenant_requires_admin_role(client, auth_header):
    headers = auth_header(action=Action.QUERY)
    response = await client.post("/v1/admin/tenants", json={"name": "Acme Legal", "industry": "legal"}, headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_and_list_tenant_as_admin(client, auth_header):
    headers = auth_header(action=Action.ADMIN)
    created = await client.post("/v1/admin/tenants", json={"name": "Acme Legal", "industry": "legal"}, headers=headers)
    assert created.status_code == 201

    listed = await client.get("/v1/admin/tenants", headers=headers)
    assert listed.status_code == 200
    assert any(t["name"] == "Acme Legal" for t in listed.json())

