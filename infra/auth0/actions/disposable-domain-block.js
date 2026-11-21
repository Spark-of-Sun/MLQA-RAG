/**
 * Pre-user-registration Action: disposable-domain-block (doc 8.2, 7.2).
 * Refuses sign-ups from throwaway email domains. The list comes from the BLOCKED_DOMAINS secret
 * (comma separated), set by OpenTofu. Abuse controls also include verified email, mandatory MFA and
 * per-IP organization-creation limits (identity service and Cloudflare).
 */
exports.onExecutePreUserRegistration = async (event, api) => {
  const email = (event.user.email ?? "").toLowerCase();
  const domain = email.split("@")[1] ?? "";
  const blocked = (event.secrets.BLOCKED_DOMAINS ?? "")
    .split(",")
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean);
  if (!domain || blocked.some((d) => domain === d || domain.endsWith(`.${d}`))) {
    api.access.deny("invalid_signup", "Please sign up with a work email address.");
  }
};
