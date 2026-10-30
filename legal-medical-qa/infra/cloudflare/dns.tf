# DNS for onekami.site. Everything the browser reaches goes through Cloudflare (proxied); the login
# domain is DNS-only because Auth0's custom domain terminates its own TLS.

resource "cloudflare_dns_record" "apex" {
  zone_id = data.cloudflare_zone.site.zone_id
  name    = var.domain
  type    = "CNAME" # flattened to A/AAAA at the apex by Cloudflare
  content = var.origin_hostname
  ttl     = 1
  proxied = true
  comment = "lmqa frontend (behind the AWS load balancer)"
}

resource "cloudflare_dns_record" "www" {
  zone_id = data.cloudflare_zone.site.zone_id
  name    = "www"
  type    = "CNAME"
  content = var.domain
  ttl     = 1
  proxied = true
}

resource "cloudflare_dns_record" "login" {
  count   = var.auth0_custom_domain_target == "" ? 0 : 1
  zone_id = data.cloudflare_zone.site.zone_id
  name    = "login"
  type    = "CNAME"
  content = var.auth0_custom_domain_target
  ttl     = 300
  proxied = false # Auth0 verifies this record directly and terminates TLS itself
  comment = "Auth0 custom domain login.${var.domain}"
}

resource "cloudflare_dns_record" "spf" {
  count   = var.spf_record == "" ? 0 : 1
  zone_id = data.cloudflare_zone.site.zone_id
  name    = var.domain
  type    = "TXT"
  content = "\"${var.spf_record}\""
  ttl     = 3600
}

resource "cloudflare_dns_record" "dmarc" {
  zone_id = data.cloudflare_zone.site.zone_id
  name    = "_dmarc"
  type    = "TXT"
  content = "\"${var.dmarc_record}\""
  ttl     = 3600
}

# The API and every internal service stay private: there is deliberately NO public record for them.
