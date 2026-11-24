/**
 * Post-login Action (design 8.2, 8.4, R-19, R-21, G2.6, G2.7). Auth0 authenticates; PostgreSQL authorizes, so this
 * Action adds facts about the authentication only, never a role the gateway would trust:
 *   <ns>/org_id         the Auth0 Organization of this login (also the standard `org_id` claim)
 *   <ns>/auth_strength  passkey | webauthn_mfa | otp_mfa | password, from event.authentication.methods
 *                       (the same names as libs/lmqa_auth/src/lmqa_auth/strength.py)
 *   <ns>/amr            the method names Auth0 reported (pinned by contracts/claims/auth-methods.json, G2.7)
 *   <ns>/authenticator  a stable ID of the authenticator used, for "distinct authenticators" on approvals
 * Audiences (DEV-10): the `main` API requires an organization and the `onboarding` API denies one. Auth0 has no
 * per-API organization setting, so the BFF client allows organizations and this Action enforces the rule per API.
 * Privileged users (app_metadata.privileged, set by the identity service for Super Admins and admins) must use a
 * phishing-resistant factor (passkey or WebAuthn); otherwise a WebAuthn factor is challenged. No backend calls.
 */
const WEBAUTHN = ["webauthn-platform", "webauthn-roaming"];

function strengthOf(methods) {
  const names = methods.map((m) => m.name);
  if (names.includes("passkey")) return "passkey";
  const second = methods.filter((m) => m.name === "mfa" || WEBAUTHN.includes(m.name) || m.name === "otp");
  if (second.some((m) => WEBAUTHN.includes(m.name) || WEBAUTHN.includes(m.type))) return "webauthn_mfa";
  if (second.length) return "otp_mfa";
  return "password";
}

exports.onExecutePostLogin = async (event, api) => {
  const ns = event.secrets.CLAIMS_NAMESPACE || "https://claims.onekami.site";
  const audience = event.resource_server ? event.resource_server.identifier : "";
  const orgsRequired = event.secrets.ORGANIZATIONS_REQUIRED === "on"; // mirrors AUTH0_ORGANIZATIONS
  if (orgsRequired && audience && audience === event.secrets.MAIN_AUDIENCE && !event.organization) {
    api.access.deny("organization_required");
    return;
  }
  if (audience && audience === event.secrets.ONBOARDING_AUDIENCE && event.organization) {
    api.access.deny("organization_not_allowed");
    return;
  }

  const methods = (event.authentication && event.authentication.methods) || [];
  const names = methods.map((m) => m.name);
  const strength = strengthOf(methods);
  const last = methods.length ? methods[methods.length - 1] : null;
  const authenticator = last ? `${last.name}:${(last.timestamp || "").slice(0, 19)}:${event.session ? event.session.id : ""}` : "";

  api.accessToken.setCustomClaim(`${ns}/auth_strength`, strength);
  api.accessToken.setCustomClaim(`${ns}/amr`, names);
  api.accessToken.setCustomClaim(`${ns}/authenticator`, authenticator);
  if (event.organization) {
    api.accessToken.setCustomClaim(`${ns}/org_id`, event.organization.id);
  }

  const privileged = event.user.app_metadata && event.user.app_metadata.privileged === true;
  if (privileged && strength !== "passkey" && strength !== "webauthn_mfa") {
    const enrolled = (event.user.enrolledFactors || []).some((f) => WEBAUTHN.includes(f.type));
    const factor = { type: "webauthn-platform" };
    const more = { additionalFactors: [{ type: "webauthn-roaming" }] };
    if (enrolled) api.authentication.challengeWith(factor, more);
    else api.authentication.enrollWith(factor, more);
  }
};

exports.strengthOf = strengthOf; // for the contract test
