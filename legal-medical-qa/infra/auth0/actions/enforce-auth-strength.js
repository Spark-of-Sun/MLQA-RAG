/**
 * Post-login Action: enforce-auth-strength (doc 8.4).
 *
 * - Blocks unverified emails.
 * - Computes `auth_strength` from the authentication methods Auth0 records for THIS session:
 *     passkey       primary login by passkey
 *     webauthn_mfa  a WebAuthn second factor (roaming or platform)
 *     otp_mfa       TOTP
 *     password      anything else
 * - Adds the namespaced claims the Gateway reads. The role claim is ADVISORY: the database decides.
 * - For a privileged user (`app_metadata.privileged`, set by the identity service) it enrolls a WebAuthn
 *   factor when none exists, otherwise challenges with WebAuthn. Recovery never downgrades to TOTP.
 *
 * The method names and types Auth0 reports are the one thing that can change under us: they are pinned by
 * contract test G2.7 against the real tenant, so a change fails the build instead of silently weakening
 * the policy. Treat the names below as the values to verify, not as truth.
 *
 * Actions never call our backend, so a backend outage cannot break login.
 */
exports.onExecutePostLogin = async (event, api) => {
  const ns = event.secrets.CLAIMS_NAMESPACE;

  if (!event.user.email_verified) {
    api.access.deny("email_not_verified", "Verify your email address, then sign in again.");
    return;
  }

  const methods = event.authentication?.methods ?? [];
  const used = (name, type) => methods.some((m) => m.name === name && (type === undefined || m.type === type));

  let strength = "password";
  if (used("passkey")) strength = "passkey";
  else if (used("mfa", "webauthn-roaming") || used("mfa", "webauthn-platform")) strength = "webauthn_mfa";
  else if (used("mfa")) strength = "otp_mfa";

  const privileged = event.user.app_metadata?.privileged === true;
  if (privileged && strength !== "passkey" && strength !== "webauthn_mfa") {
    const enrolled = (event.user.enrolledFactors ?? []).some((f) => f.type?.startsWith("webauthn"));
    const factors = [{ type: "webauthn-roaming" }, { type: "webauthn-platform" }];
    if (enrolled) api.authentication.challengeWithAny(factors);
    else api.authentication.enrollWithAny(factors);
    return; // Auth0 re-runs this Action after the factor completes
  }

  api.accessToken.setCustomClaim(`${ns}/auth_strength`, strength);
  api.idToken.setCustomClaim(`${ns}/auth_strength`, strength);
  const role = event.authorization?.roles?.[0];
  if (role) api.accessToken.setCustomClaim(`${ns}/role`, role);
};
