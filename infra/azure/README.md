# Microsoft Azure Infrastructure for MLQA-RAG

This directory specifies the Microsoft Azure cloud infrastructure configuration for the MLQA-RAG platform.

## Architecture Components

1. **Object Storage (Azure Blob Storage)**
   - Resource: Storage Account (Hierarchical namespace or standard general-purpose v2)
   - Containers:
     - `documents`: Raw ingested PDF, HTML, and text documents partitioned by tenant (`{tenant_id}/{document_id}`).
     - `audit-anchors`: Immutable external root hash checkpoints for the audit chain.
     - `tombstones`: Cryptographic shredding markers (`{tenant_id}/{document_id}.tombstone`).
   - Security: TLS 1.3 enforced, public network access restricted, customer-managed keys (CMK) envelope encryption.

2. **Key Management (Azure Key Vault)**
   - Resource: Azure Key Vault (Premium / HSM-backed or Standard)
   - Keys:
     - Trust Root Key: Hardware-backed RSA/AES master key for tenant key wrapping.
     - Organization Keys: Tenant-specific key alias prefix `lmqa-org-`.
   - Operations: Key wrap / unwrap, encrypt / decrypt for envelope data keys.

3. **Identity & Access Management (Microsoft Entra ID)**
   - Service Principal / Workload Identity:
     - `AZURE_TENANT_ID`: Active Entra ID Tenant ID.
     - `AZURE_CLIENT_ID`: Service Principal Client / Application ID.
     - `AZURE_CLIENT_SECRET`: Client Secret for headless / CI/CD operations (or federated OIDC credentials).
   - Roles:
     - Storage Blob Data Contributor on target storage containers.
     - Key Vault Crypto Service Encryption User on target key vault keys.
