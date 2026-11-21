# Edge security for onekami.site: strict TLS, HSTS, the managed WAF ruleset, a hard block on the
# internal path prefix, and rate limits on the sign-in and onboarding routes (the join-code guessing surface).

locals {
  zone_id = data.cloudflare_zone.site.zone_id
  settings = {
    ssl                      = "strict" # Cloudflare validates the origin certificate: no flexible TLS
    min_tls_version          = "1.2"
    tls_1_3                  = "on"
    always_use_https         = "on"
    automatic_https_rewrites = "on"
    opportunistic_encryption = "on"
    browser_check            = "on"
    security_level           = "medium"
    http3                    = "on"
    email_obfuscation        = "off" # never rewrite our HTML
    rocket_loader            = "off" # it would break the nonce-based Content Security Policy
    mirage                   = "off"
    polish                   = "off"
    response_buffering       = "off" # the streamed answer must not be buffered (doc 4.8)
  }
}

resource "cloudflare_zone_setting" "this" {
  for_each   = local.settings
  zone_id    = local.zone_id
  setting_id = each.key
  value      = each.value
}

# HSTS at the edge as well as at the application (preload-ready).
resource "cloudflare_zone_setting" "hsts" {
  zone_id    = local.zone_id
  setting_id = "security_header"
  value = {
    strict_transport_security = {
      enabled            = true
      max_age            = 63072000
      include_subdomains = true
      preload            = true
      nosniff            = true
    }
  }
}

resource "cloudflare_ruleset" "waf_custom" {
  zone_id     = local.zone_id
  name        = "lmqa custom firewall rules"
  description = "Block what must never be public"
  kind        = "zone"
  phase       = "http_request_firewall_custom"
  rules = [
    {
      action      = "block"
      description = "Internal service paths are never public"
      expression  = "starts_with(http.request.uri.path, \"/internal/\") or starts_with(http.request.uri.path, \"/ops/\")"
      enabled     = true
    },
    {
      action      = "block"
      description = "Only the methods the API uses"
      expression  = "not http.request.method in {\"GET\" \"HEAD\" \"POST\" \"PUT\" \"PATCH\" \"DELETE\" \"OPTIONS\"}"
      enabled     = true
    },
  ]
}

resource "cloudflare_ruleset" "waf_managed" {
  zone_id     = local.zone_id
  name        = "lmqa managed WAF"
  description = "Cloudflare managed ruleset"
  kind        = "zone"
  phase       = "http_request_firewall_managed"
  rules = [{
    action = "execute"
    action_parameters = {
      id = "efb7b8c949ac4650a09736fc376e9aee" # Cloudflare Managed Ruleset
    }
    expression  = "true"
    description = "Execute the Cloudflare Managed Ruleset"
    enabled     = true
  }]
}

# Join codes are 115 to 275 bit secrets, but the guessing surface is still limited at the edge (doc 7.6).
resource "cloudflare_ruleset" "rate_limits" {
  zone_id     = local.zone_id
  name        = "lmqa rate limits"
  description = "Sign-in and onboarding"
  kind        = "zone"
  phase       = "http_ratelimit"
  rules = [
    {
      action      = "block"
      description = "Sign-in and callback"
      expression  = "starts_with(http.request.uri.path, \"/auth/\")"
      enabled     = true
      ratelimit = {
        characteristics     = ["ip.src", "cf.colo.id"]
        period              = 60
        requests_per_period = 30
        mitigation_timeout  = 600
      }
    },
    {
      action      = "block"
      description = "Join codes and organization creation"
      expression  = "starts_with(http.request.uri.path, \"/api/v1/onboarding/\")"
      enabled     = true
      ratelimit = {
        characteristics     = ["ip.src", "cf.colo.id"]
        period              = 60
        requests_per_period = 10
        mitigation_timeout  = 900
      }
    },
  ]
}
