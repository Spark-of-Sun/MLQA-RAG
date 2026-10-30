# The two APIs, the applications and the roles (doc 8.2).
#
# main:       organization REQUIRED, RS256, 10 minute access tokens. An organization-less token cannot reach it.
# onboarding: organization DENIED, only the onboarding endpoints accept it (the first login of a new user).

resource "auth0_resource_server" "main" {
  name                                            = "lmqa main API (${var.environment})"
  identifier                                      = local.api_main
  signing_alg                                     = "RS256"
  token_lifetime                                  = 600
  allow_offline_access                            = true # refresh tokens, rotated with reuse detection on the client
  skip_consent_for_verifiable_first_party_clients = true
  enforce_policies                                = false
  token_dialect                                   = "access_token"
}

resource "auth0_resource_server" "onboarding" {
  name                                            = "lmqa onboarding API (${var.environment})"
  identifier                                      = local.api_onboarding
  signing_alg                                     = "RS256"
  token_lifetime                                  = 600
  allow_offline_access                            = true
  skip_consent_for_verifiable_first_party_clients = true
}

# Regular Web Application (NOT a single-page app): Authorization Code with PKCE, exact callback URLs only.
resource "auth0_client" "web_bff" {
  name                          = "lmqa web-bff (${var.environment})"
  app_type                      = "regular_web"
  oidc_conformant               = true
  is_first_party                = true
  callbacks                     = ["${var.app_base_url}/auth/callback"]
  allowed_logout_urls           = [var.app_base_url]
  web_origins                   = []
  grant_types                   = ["authorization_code", "refresh_token"]
  organization_usage            = "allow"
  organization_require_behavior = "no_prompt"

  jwt_configuration {
    alg                 = "RS256"
    lifetime_in_seconds = 600
  }

  refresh_token {
    rotation_type                = "rotating"
    expiration_type              = "expiring"
    leeway                       = 0
    token_lifetime               = 28800 # the privileged absolute session limit: 8 hours
    infinite_token_lifetime      = false
    infinite_idle_token_lifetime = false
    idle_token_lifetime          = 900 # the privileged idle limit: 15 minutes
  }
}

resource "auth0_client_grant" "bff_main" {
  client_id = auth0_client.web_bff.client_id
  audience  = auth0_resource_server.main.identifier
  scopes    = []
}

resource "auth0_client_grant" "bff_onboarding" {
  client_id = auth0_client.web_bff.client_id
  audience  = auth0_resource_server.onboarding.identifier
  scopes    = []
}

# The identity service's machine-to-machine client: the only holder of Management API access (doc 8.8).
# Minimal scopes: organizations, members, roles, users (read/update), authentication methods, sessions and refresh tokens.
resource "auth0_client" "identity_m2m" {
  name            = "lmqa identity-m2m (${var.environment})"
  app_type        = "non_interactive"
  is_first_party  = true
  oidc_conformant = true
  grant_types     = ["client_credentials"]
}

data "auth0_resource_server" "management" {
  identifier = "https://${var.domain}/api/v2/" # replace with the tenant's own Management API identifier if no custom domain
}

resource "auth0_client_grant" "identity_management" {
  client_id = auth0_client.identity_m2m.client_id
  audience  = data.auth0_resource_server.management.identifier
  scopes = [
    "read:users", "update:users", "read:organizations", "create:organizations", "update:organizations",
    "create:organization_members", "read:organization_members", "delete:organization_members",
    "create:organization_member_roles", "read:organization_member_roles", "read:roles",
    "read:authentication_methods", "delete:authentication_methods",
    "read:sessions", "delete:sessions", "read:refresh_tokens", "delete:refresh_tokens",
  ]
}

# Three roles, defined once per tenant and assigned per organization membership by the identity service only.
resource "auth0_role" "role" {
  for_each    = toset(["super_admin", "admin", "tenant"])
  name        = each.key
  description = "lmqa ${each.key} (advisory: the database decides, doc 8.3)"
}
