"""Key management (blueprint 12): providers, envelope encryption, the key ring with its DEK cache, field
encryption, KeyGuard."""

from lmqa_keys.audit_keys import AuditKeyProvisioning, provision_audit_keys
from lmqa_keys.envelope import (
    Binding,
    DecryptionError,
    decrypt_stream,
    decrypt_text,
    decrypt_value,
    encrypt_stream,
    encrypt_text,
    encrypt_value,
)
from lmqa_keys.fields import Field, FieldCipher, Provisioner, normalize_email
from lmqa_keys.keyring import AuditKey, DekCache, KeyRing, generate_audit_keypair
from lmqa_keys.providers import (
    AwsKmsProvider,
    KeyProvider,
    KeyProviderError,
    KeyState,
    KeyUnavailableError,
    OpenBaoProvider,
    provider_from_settings,
)


def field_cipher_from_settings(provision: Provisioner | None = None) -> FieldCipher:
    """The process-wide field cipher on the configured provider (KMS_PROVIDER: OpenBao locally, AWS KMS in the
    cloud). Credentials are read by setting name inside the provider; nothing here sees them."""
    return FieldCipher(KeyRing(provider_from_settings()), provision)


__all__ = [
    "AuditKey",
    "AuditKeyProvisioning",
    "AwsKmsProvider",
    "Binding",
    "DecryptionError",
    "DekCache",
    "Field",
    "FieldCipher",
    "KeyProvider",
    "KeyProviderError",
    "KeyRing",
    "KeyState",
    "KeyUnavailableError",
    "OpenBaoProvider",
    "Provisioner",
    "decrypt_stream",
    "decrypt_text",
    "decrypt_value",
    "encrypt_stream",
    "encrypt_text",
    "encrypt_value",
    "field_cipher_from_settings",
    "generate_audit_keypair",
    "normalize_email",
    "provider_from_settings",
    "provision_audit_keys",
]
