# Auth0 tenants as code (blueprint 8, 4.6, G0.7, G2.7, G11.1). One state per tenant: dev, ci, staging, prod.
#   export AUTH0_DOMAIN=... AUTH0_CLIENT_ID=... AUTH0_CLIENT_SECRET=...   (a dedicated Terraform M2M app)
#   tofu -chdir=infra/auth0 plan -var env=ci -var app_base_url=http://localhost:3000
# Drift is a gate failure: `tofu plan -detailed-exitcode` must exit 0 for dev and ci (G0.7).

terraform {
  required_version = ">= 1.8"
  required_providers {
    auth0 = { source = "auth0/auth0", version = "~> 1.30" }
  }
}

variable "env" { type = string }
variable "app_base_url" { type = string }
variable "api_identifier" {
  type    = string
  default = "https://api.onekami.site"
}
variable "onboarding_api_identifier" {
  type    = string
  default = "https://onboarding.onekami.site"
}
# Free-plan gates. MFA factors (OTP, WebAuthn) and breached-password detection need a paid Auth0 plan; passkeys on
# the database connection do not. Off: Guardian stays as found (all factors off, no MFA policy).
variable "paid_features" {
  type    = bool
  default = false
}
# Mirrors AUTH0_ORGANIZATIONS in .env. Off: the Action does not yet deny a `main` token without an organization, so
# current sign-in keeps working until the identity saga creates Organizations (lmqa_auth.verifier uses the same flag).
variable "organizations_required" {
  type    = bool
  default = false
}
# Appendix C maximum is 600 s. The BFF does not request offline_access yet, so a 600 s token cannot be refreshed and
# API calls fail 10 minutes after sign-in. Keep the tenant's current value (86400) in dev until the BFF refreshes.
variable "access_token_lifetime" {
  type    = number
  default = 600
}
variable "claims_namespace" {
  type    = string
  default = "https://claims.onekami.site"
}

provider "auth0" {}

locals {
  callback = "${var.app_base_url}/auth/callback"
  prod     = var.env == "prod"
}

# --- tenant-wide security posture ---------------------------------------------------------------------------------
resource "auth0_tenant" "this" {
  friendly_name         = "Cyte ${var.env}"
  session_lifetime      = 8 # hours, privileged absolute maximum (Appendix C)
  idle_session_lifetime = 0.25
  allowed_logout_urls   = [var.app_base_url]
  enabled_locales       = ["en"]
  flags {
    disable_clickjack_protection_headers   = false
    enable_public_signup_user_exists_error = false
    revoke_refresh_token_grant             = true
  }
  sessions { oidc_logout_prompt_enabled = false }
}

resource "auth0_guardian" "mfa" {
  policy = var.paid_features ? "all-applications" : "never"
  otp    = var.paid_features
  webauthn_roaming {
    enabled           = var.paid_features
    user_verification = "required"
  }
  webauthn_platform {
    enabled = var.paid_features
  }
  email = false # Appendix C: email and SMS OTP factors disabled
  # No phone block: SMS stays disabled, and the legacy phone provider endpoint is refused on this tenant (403).
}

resource "auth0_attack_protection" "this" {
  brute_force_protection {
    enabled      = true
    max_attempts = 10
    mode         = "count_per_identifier_and_ip"
    shields      = ["block", "user_notification"]
  }
  breached_password_detection {
    enabled = var.paid_features
    method  = "standard"
    shields = ["block", "user_notification"]
  }
  suspicious_ip_throttling {
    enabled = true
    shields = ["admin_notification", "block"]
  }
}

# --- connection with passkeys -----------------------------------------------------------------------------------
resource "auth0_connection" "users" {
  name     = "lmqa-${var.env}-users"
  strategy = "auth0"
  options {
    password_policy        = "excellent"
    brute_force_protection = true
    disable_signup         = false
    authentication_methods {
      passkey {
        enabled = true
      }
      password {
        enabled = true
      }
    }
    passkey_options {
      challenge_ui                   = "both"
      progressive_enrollment_enabled = true
      local_enrollment_enabled       = true
    }
  }
}

# --- APIs: main data/control audience and a separate onboarding audience (8.2, DEV-10) ---------------------------
# `main` requires an Auth0 Organization and `onboarding` denies one. Auth0 has no per-API organization switch, so the
# clients below use organization_usage = "allow" (one login client serves both APIs) and the post-login Action denies
# a `main` token without an organization and an `onboarding` token with one. lmqa_auth.verifier checks it again.
resource "auth0_resource_server" "main" {
  name                                            = "Cyte API ${var.env}"
  identifier                                      = var.api_identifier
  signing_alg                                     = "RS256"
  token_lifetime                                  = var.access_token_lifetime
  skip_consent_for_verifiable_first_party_clients = true
  enforce_policies                                = true
  token_dialect                                   = "access_token_authz"
}
resource "auth0_resource_server" "onboarding" {
  name                                            = "Cyte onboarding ${var.env}"
  identifier                                      = var.onboarding_api_identifier
  signing_alg                                     = "RS256"
  token_lifetime                                  = 600
  skip_consent_for_verifiable_first_party_clients = true
}

# --- Auth0 Organizations: one per Organization, created at run time by the identity service saga (R-19.2), never
# here. Login clients allow organizations; members join by invitation or join code, not by connection auto-membership.

# --- the BFF: Regular Web Application, Authorization Code + PKCE (4.8) -------------------------------------------
resource "auth0_client" "bff" {
  name                          = "Cyte web ${var.env}"
  app_type                      = "regular_web"
  callbacks                     = [local.callback]
  allowed_logout_urls           = [var.app_base_url]
  web_origins                   = [var.app_base_url]
  oidc_conformant               = true
  grant_types                   = ["authorization_code", "refresh_token"]
  organization_usage            = "allow"
  organization_require_behavior = "post_login_prompt"
  refresh_token {
    rotation_type       = "rotating"
    expiration_type     = "expiring"
    token_lifetime      = 28800
    idle_token_lifetime = 900
    leeway              = 0
  }
  jwt_configuration { alg = "RS256" }
}
resource "auth0_client_credentials" "bff" {
  client_id             = auth0_client.bff.id
  authentication_method = "client_secret_post"
}

# Auth harness (Stage 0): a minimal real relying party for backend tests before the frontend exists.
resource "auth0_client" "auth_harness" {
  count              = local.prod ? 0 : 1
  name               = "Cyte auth harness ${var.env}"
  app_type           = "regular_web"
  callbacks          = ["http://127.0.0.1:8765/callback"]
  oidc_conformant    = true
  grant_types        = ["authorization_code", "refresh_token"]
  organization_usage = "allow"
}
resource "auth0_client_credentials" "auth_harness" {
  count                 = local.prod ? 0 : 1
  client_id             = auth0_client.auth_harness[0].id
  authentication_method = "client_secret_post"
}

# Only the login clients may use the database connection; the M2M client has no interactive login.
resource "auth0_connection_clients" "users" {
  connection_id   = auth0_connection.users.id
  enabled_clients = concat([auth0_client.bff.client_id], [for c in auth0_client.auth_harness : c.client_id])
}

# --- identity service M2M with only the scopes it needs (8.8, R-25, G2.11) -----------------------------------------
# The only client with a Management API grant. Its secret goes to the identity-worker's own secret (AUTH0_M2M_*),
# never to the Gateway, BFF or other services (tests/contract/test_stage2_auth0_config.py checks the code side).
# The list must equal services/identity/src/identity/auth0_mgmt.py SCOPES, which refuses a token carrying more.
resource "auth0_client" "identity_m2m" {
  name        = "Cyte identity service ${var.env}"
  app_type    = "non_interactive"
  grant_types = ["client_credentials"]
}
resource "auth0_client_grant" "identity_m2m" {
  client_id = auth0_client.identity_m2m.id
  audience  = "https://${data.auth0_tenant.current.domain}/api/v2/"
  scopes = [
    "read:organizations", "create:organizations", "update:organizations", "delete:organizations",
    "read:organization_members", "create:organization_members", "delete:organization_members",
    "read:organization_member_roles", "create:organization_member_roles", "delete:organization_member_roles",
    "create:organization_connections", "read:roles", "read:users", "update:users", "delete:refresh_tokens",
    "delete:sessions", "read:users_app_metadata", "update:users_app_metadata",
  ]
}
data "auth0_tenant" "current" {}

# --- organization roles (names only; authorization stays in PostgreSQL) ------------------------------------------
resource "auth0_role" "roles" {
  for_each    = toset(["super_admin", "admin", "tenant"])
  name        = "lmqa_${each.key}"
  description = "Membership marker; PostgreSQL decides what it allows"
}

# --- the post-login Action -----------------------------------------------------------------------------------------
resource "auth0_action" "post_login" {
  name    = "lmqa-post-login"
  runtime = "node22"
  deploy  = true
  code    = file("${path.module}/actions/post-login.js")
  supported_triggers {
    id      = "post-login"
    version = "v3"
  }
  secrets {
    name  = "CLAIMS_NAMESPACE"
    value = var.claims_namespace
  }
  secrets {
    name  = "ORGANIZATIONS_REQUIRED"
    value = var.organizations_required ? "on" : "off"
  }
  secrets {
    name  = "MAIN_AUDIENCE"
    value = auth0_resource_server.main.identifier
  }
  secrets {
    name  = "ONBOARDING_AUDIENCE"
    value = auth0_resource_server.onboarding.identifier
  }
}
resource "auth0_trigger_actions" "post_login" {
  trigger = "post-login"
  actions {
    id           = auth0_action.post_login.id
    display_name = auth0_action.post_login.name
  }
}

output "bff_client_id" { value = auth0_client.bff.client_id }
output "identity_m2m_client_id" { value = auth0_client.identity_m2m.client_id }
output "connection_id" { value = auth0_connection.users.id }
output "role_ids" { value = { for k, r in auth0_role.roles : k => r.id } }

# Values the application reads from .env (names match .env.example).
output "AUTH0_AUDIENCE_MAIN" { value = auth0_resource_server.main.identifier }
output "AUTH0_AUDIENCE_ONBOARDING" { value = auth0_resource_server.onboarding.identifier }
output "AUTH0_CONNECTION_ID" { value = auth0_connection.users.id }
output "AUTH0_ROLE_ID_SUPER_ADMIN" { value = auth0_role.roles["super_admin"].id }
output "AUTH0_ROLE_ID_ADMIN" { value = auth0_role.roles["admin"].id }
output "AUTH0_ROLE_ID_TENANT" { value = auth0_role.roles["tenant"].id }
output "AUTH0_CLIENT_ID_HARNESS" { value = one(auth0_client.auth_harness[*].client_id) }
output "AUTH0_CLIENT_SECRET_HARNESS" {
  value     = one(auth0_client_credentials.auth_harness[*].client_secret)
  sensitive = true
}
