/**
 * Routes and who may see them (doc 17.1). This is a convenience layer, never the control: the Gateway
 * allow-list and PostgreSQL row-level security decide. A forbidden route is a 404, so its existence is
 * not revealed. The role comes from the Gateway (`/v1/me`), never from anything the browser holds.
 */
export type Role = "super_admin" | "admin" | "tenant";
export type MemberState = "pending_approval" | "active" | "suspended" | "rejected" | "removed";

export interface Me {
  user_id: string;
  role: Role;
  state: MemberState;
  org_state: string;
  workspace_id: string | null;
  capabilities: string[];
}

const ROUTES: Record<string, readonly Role[]> = {
  "/chat": ["admin", "tenant"],
  "/library": ["admin", "tenant"],
  "/audit": ["super_admin", "admin", "tenant"],
  "/manage-admins": ["super_admin"],
  "/governance": ["super_admin"],
  "/manage-tenants": ["admin"],
  "/walls": ["admin"],
  "/review": ["admin"],
  "/account": ["super_admin", "admin", "tenant"],
};

export type Access = "allow" | "redirect" | "notfound" | "blocked";

/** What to do when a principal asks for `path`. */
export function accessFor(me: Me | null, path: string): { kind: Access; to?: string } {
  if (me === null) return { kind: "redirect", to: "/onboarding" };
  if (me.state !== "active" || me.org_state !== "active") {
    return path === "/account" ? { kind: "allow" } : { kind: "blocked" };
  }
  const base = "/" + (path.split("/")[1] ?? "");
  const allowed = ROUTES[base];
  if (allowed === undefined) return { kind: "notfound" };
  if (allowed.includes(me.role)) return { kind: "allow" };
  // A Super Admin who types /chat is sent home; every other forbidden route is a plain 404.
  if (me.role === "super_admin" && (base === "/chat" || base === "/library")) {
    return { kind: "redirect", to: "/manage-admins" };
  }
  return { kind: "notfound" };
}

/** The page a signed-in principal lands on. */
export function homeFor(me: Me): string {
  if (me.state !== "active" || me.org_state !== "active") return "/onboarding";
  return me.role === "super_admin" ? "/manage-admins" : "/chat";
}

export const NAV: readonly { href: string; label: string; roles: readonly Role[] }[] = [
  { href: "/chat", label: "Ask", roles: ["admin", "tenant"] },
  { href: "/library", label: "Library", roles: ["admin", "tenant"] },
  { href: "/manage-admins", label: "Manage admins", roles: ["super_admin"] },
  { href: "/manage-tenants", label: "Manage tenants", roles: ["admin"] },
  { href: "/walls", label: "Ethical walls", roles: ["admin"] },
  { href: "/account", label: "Account", roles: ["super_admin", "admin", "tenant"] },
];
