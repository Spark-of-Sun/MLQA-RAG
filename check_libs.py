"""One-off smoke test for libs/common and libs/prompt_registry_client.
Not part of the service test suites — just a quick local sanity check
before wiring these into an actual service."""

from datetime import date

from common.models import Chunk, ConfidentialityTier, Citation, AuditEvent, Tenant, TenantIndustry, RoleScope, Action
from common.auth.jwt import create_session_jwt, decode_session_jwt
from common.auth.service_token import verify_internal_service_key, ServiceAuthError
from common.security.encryption import encrypt_field, decrypt_field
from common.logging import configure_logging, get_logger
from prompt_registry_client import PromptRegistryClient

print("== models ==")
chunk = Chunk(
    chunk_id="c1", document_id="doc1", tenant_id="t1",
    matter_or_patient_id="matter-123", text="The term is 12 months.",
    page=4, section="4.2", confidentiality_tier=ConfidentialityTier.PRIVILEGED,
    effective_date=date(2026, 1, 1),
)
print(chunk.to_prompt_tag())
assert chunk.to_prompt_tag() == '<chunk id="c1" doc="doc1" page="4" section="4.2">'

role = RoleScope(tenant_id="t1", matter_or_patient_id="matter-123", action=Action.QUERY)
assert role.covers("t1", "matter-123", Action.QUERY)
assert not role.covers("t1", "matter-999", Action.QUERY)
print("models OK")

print("== encryption ==")
ct = encrypt_field("patient notes: elevated BP")
assert decrypt_field(ct) == "patient notes: elevated BP"
print("encryption roundtrip OK")

print("== jwt ==")
token = create_session_jwt(user_id="u1", tenant_id="t1", roles=[role])
claims = decode_session_jwt(token)
assert claims.user_id == "u1"
assert claims.roles[0].matter_or_patient_id == "matter-123"
print("jwt roundtrip OK")

print("== service token ==")
import os
verify_internal_service_key(os.environ["INTERNAL_SERVICE_API_KEY"])  # should not raise
try:
    verify_internal_service_key("wrong-key")
    raise SystemExit("expected ServiceAuthError, got none")
except ServiceAuthError:
    print("service token check OK (correctly rejected bad key)")

print("== logging ==")
configure_logging(service_name="check_libs")
log = get_logger(__name__)
log.info("smoke_test_log_line", chunk_id=chunk.chunk_id)

print("== prompt registry client (local-file backend) ==")
client = PromptRegistryClient(backend="local-file", templates_dir="prompts/templates")
client.record_eval_result(template_version="v0-smoke-test", pass_rate=1.0, question_count=1)
print("wrote prompts/templates/eval_history.jsonl")

print("\nALL CHECKS PASSED")