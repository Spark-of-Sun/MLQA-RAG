resource "auth0_action" "enforce_auth_strength" {
  name    = "enforce-auth-strength"
  runtime = "node22"
  deploy  = true
  code    = file("${path.module}/actions/enforce-auth-strength.js")
  supported_triggers {
    id      = "post-login"
    version = "v3"
  }
  secrets {
    name  = "CLAIMS_NAMESPACE"
    value = var.claims_namespace
  }
}

resource "auth0_action" "disposable_domain_block" {
  name    = "disposable-domain-block"
  runtime = "node22"
  deploy  = true
  code    = file("${path.module}/actions/disposable-domain-block.js")
  supported_triggers {
    id      = "pre-user-registration"
    version = "v2"
  }
  secrets {
    name  = "BLOCKED_DOMAINS"
    value = join(",", var.blocked_email_domains)
  }
}

resource "auth0_trigger_actions" "post_login" {
  trigger = "post-login"
  actions {
    id           = auth0_action.enforce_auth_strength.id
    display_name = auth0_action.enforce_auth_strength.name
  }
}

resource "auth0_trigger_actions" "pre_registration" {
  trigger = "pre-user-registration"
  actions {
    id           = auth0_action.disposable_domain_block.id
    display_name = auth0_action.disposable_domain_block.name
  }
}

# MFA is always on. WebAuthn (roaming and platform) and TOTP are allowed; SMS, voice and email OTP are
# disabled (SIM-swap and phishing exposure, doc 8.2). Passkeys are enabled on the database connection.
resource "auth0_guardian" "mfa" {
  policy = "all-applications"
  webauthn_roaming {
    enabled           = true
    user_verification = "required"
  }
  webauthn_platform {
    enabled = true
  }
  otp = true
  phone {
    enabled = false
  }
  email = false
}

resource "auth0_connection" "database" {
  name     = "lmqa-users-${var.environment}"
  strategy = "auth0"
  options {
    password_policy        = "excellent"
    brute_force_protection = true
    requires_username      = false
    disable_signup         = false
    password_history {
      enable = true
      size   = 5
    }
    password_no_personal_info {
      enable = true
    }
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
      local_enrollment_enabled       = true
      progressive_enrollment_enabled = true
    }
  }
}

# Organizations: automatic membership stays OFF; only the identity service adds members (doc 8.9).
resource "auth0_connection_clients" "database" {
  connection_id   = auth0_connection.database.id
  enabled_clients = [auth0_client.web_bff.client_id]
}

resource "auth0_attack_protection" "this" {
  breached_password_detection {
    enabled                      = true
    shields                      = ["block", "admin_notification"]
    admin_notification_frequency = ["immediately"]
    method                       = "standard"
  }
  suspicious_ip_throttling {
    enabled = true
    shields = ["block", "admin_notification"]
  }
  brute_force_protection {
    enabled      = true
    max_attempts = 5
    mode         = "count_per_identifier_and_ip"
    shields      = ["block", "user_notification"]
  }
}

output "web_bff_client_id" {
  value = auth0_client.web_bff.client_id
}

output "identity_m2m_client_id" {
  value = auth0_client.identity_m2m.client_id
}

output "main_audience" {
  value = auth0_resource_server.main.identifier
}

output "onboarding_audience" {
  value = auth0_resource_server.onboarding.identifier
}
