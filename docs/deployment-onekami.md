# Deploying to onekami.site (Cloudflare in front, AWS behind)

**Read first.** This guide has two paths. **Path A (staging on one host)** is the fastest way to see the
whole system running and is what to do first. **Path B (production on EKS)** needs work that is *not* in this
repository yet (listed at the end). Nothing here has been executed against a real account: it was written
and validated (`tofu validate`, YAML checks) but never applied. Expect to fix small things on first contact.

What you provide (none of these exist in the repository; `.env` holds `<PLACEHOLDERS>`):

| You provide | Where it goes |
| --- | --- |
| An Auth0 tenant (plan with Organizations and MFA; **Enterprise plus the BAA add-on before any PHI**) | `infra/auth0`, `.env` `AUTH0_*` |
| An AWS account (a second, separate "vault" account for escrow keys in production) | `infra/aws`, `.env` `AWS_*` |
| Your Cloudflare account with `onekami.site` added as a zone, and an API token scoped to that zone | `infra/cloudflare`, `CLOUDFLARE_*` |
| An LLM provider key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`), under a no-retention contract (and a BAA for medical) | `.env` |
| SMTP for notifications; an on-call webhook | `.env` |

## Path A: staging on one EC2 host with Docker Compose

1. **Cloudflare.** Add `onekami.site` to Cloudflare and switch the registrar's nameservers to Cloudflare's. Create an API
   token limited to this zone (DNS edit, Zone Settings edit, WAF/Firewall edit). `export CLOUDFLARE_API_TOKEN=...`.
2. **Auth0.** Create the tenant and a *management* machine-to-machine application used only by OpenTofu
   (`AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET` in your shell, not in `.env`). Then:
   ```bash
   cd infra/auth0 && tofu init && tofu apply -var environment=staging -var app_base_url=https://onekami.site
   ```
   Copy the outputs into `.env`: `AUTH0_CLIENT_ID_BFF`, `AUTH0_M2M_CLIENT_ID`, the two audiences. Fetch the two client
   secrets from the Auth0 dashboard. Add a custom domain `login.onekami.site` in Auth0, then re-apply Cloudflare with
   `-var auth0_custom_domain_target=<the CNAME Auth0 shows>`.
   **Then pin the Action's method names** (gate G2.7): log in once and record the `authentication.methods` the tenant
   reports; the Action in `infra/auth0/actions/enforce-auth-strength.js` assumes `passkey` and `mfa` with a `type`.
3. **AWS.** Create two IAM roles in your account, `keyguard-destroyer` and `key-admin` (MFA required; nobody assumes them
   day to day). Then:
   ```bash
   cd infra/aws && tofu init && tofu apply -var environment=staging -var deployment_mode=single_host \
     -var keyguard_destroyer_role_arn=arn:aws:iam::<acct>:role/keyguard-destroyer \
     -var key_admin_role_arn=arn:aws:iam::<acct>:role/key-admin -var security_oncall_email=you@onekami.site
   ```
   Note the outputs (trust-root key id, bucket names, `host_instance_profile`). Confirm the SNS email subscription.
4. **Host.** Launch one Linux instance (4 vCPU / 16 GB or more: the ML models need the memory) with the
   `host_instance_profile` attached and Docker installed. Open only 443 (and 22 from your IP) in its security group,
   and put an AWS load balancer or Cloudflare Tunnel in front. Copy this repository to it.
5. **Secrets.** `make env FORCE=1` fills `.env` with strong random local secrets and leaves third-party values as
   placeholders. Then edit `.env`: set `APP_ENV=staging`, `KMS_PROVIDER=aws`, `AWS_REGION`, `AWS_ACCOUNT_ID`,
   `KMS_TRUST_ROOT_ID` (from step 3), `KEYGUARD_APPROVER_ROLE_ARN`, `KEYGUARD_ADMIN_ROLE_ARN`, `OBJECT_STORE_ENDPOINT=` (empty for
   real S3), `OBJECT_STORE_BUCKET`, `APP_BASE_URL=https://onekami.site`, the Auth0 values, the LLM key. Run `make doctor` until
   nothing required is MISSING. The `openbao` compose profile is for local keys only; do not enable it with real data.
6. **Start.** `docker compose up -d --build` then `make migrate` (the override file exposes Postgres on localhost only).
   The first start downloads the embedding and re-ranking models and builds the NLI image layer.
7. **DNS.** In `infra/cloudflare`: `tofu apply -var account_id=<id> -var origin_hostname=<your load balancer hostname>`.
8. **Smoke test.** Open https://onekami.site, sign up, create an organization, generate the Organization Code, join a
   second browser as an admin, approve, upload a document from `corpus/data` (run `make load-corpus` to fetch real public
   documents), and ask a question. Expect either a cited answer or the refusal sentence. Never real customer data on staging.
9. **Calibrate before trusting answers.** `NLI_THRESHOLD` and `RERANK_THRESHOLD` are *calibration results*. The shipped
   defaults are uncalibrated placeholders and the services log that at start-up. Label at least 300 sentence/passage pairs
   per domain with a qualified attorney or clinician and set the thresholds from precision 0.99 (gate G7.3).

## Path B: production on EKS (not complete)

Use `deployment_mode = eks` (one least-privilege IAM role per service), `infra/k8s/overlays/production`, and managed
PostgreSQL 18 with PgBouncer, Valkey and an in-cluster Qdrant. Still to build before go-live (all tracked in
`docs/STATUS.md`): the VPC / EKS / RDS / Valkey infrastructure code, the KeyGuard auto-cancel responder Lambda, the
`ops` operator plane and governance requests, successor transfer and owner recovery, the OCR review UI, an OCR engine,
Playwright/axe tests, the load, chaos and isolation-at-scale suites, an external penetration test and counsel sign-off.
