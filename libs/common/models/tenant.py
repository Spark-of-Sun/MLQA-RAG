from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class TenantIndustry(str, Enum):
    LEGAL = "legal"
    MEDICAL = "medical"


class Action(str, Enum):
    READ = "read"
    QUERY = "query"
    EXPORT = "export"
    ADMIN = "admin"


class Tenant(BaseModel):
    tenant_id: str
    name: str
    industry: TenantIndustry


class RoleScope(BaseModel):
    """Role scoped to tenant x matter/patient x action, per
    docs/architecture.md §7 (RBAC). None for matter_or_patient_id means
    the grant applies to every matter/patient in the tenant.
    """

    tenant_id: str
    matter_or_patient_id: str | None = None
    action: Action

    def covers(self, tenant_id: str, matter_or_patient_id: str, action: Action) -> bool:
        if self.tenant_id != tenant_id:
            return False
        if self.action != action and self.action != Action.ADMIN:
            return False
        if self.matter_or_patient_id is None:
            return True
        return self.matter_or_patient_id == matter_or_patient_id
