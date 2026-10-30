import { describe, expect, it } from "vitest";
import { accessFor, homeFor, NAV, type Me } from "@/lib/capabilities";
import { buildCsp, newNonce } from "@/lib/csp";

const me = (role: Me["role"], over: Partial<Me> = {}): Me => ({
  user_id: "u1", role, state: "active", org_state: "active", workspace_id: "w1", capabilities: [], ...over,
});

describe("route matrix (doc 17.1, G8.1 helper half)", () => {
  const cases: [Me["role"], string, string][] = [
    ["super_admin", "/manage-admins", "allow"], ["super_admin", "/governance", "allow"], ["super_admin", "/audit", "allow"],
    ["super_admin", "/manage-tenants", "notfound"], ["super_admin", "/walls", "notfound"], ["super_admin", "/review", "notfound"],
    ["admin", "/chat", "allow"], ["admin", "/library", "allow"], ["admin", "/manage-tenants", "allow"], ["admin", "/walls", "allow"],
    ["admin", "/manage-admins", "notfound"], ["admin", "/governance", "notfound"],
    ["tenant", "/chat", "allow"], ["tenant", "/library", "allow"], ["tenant", "/audit", "allow"],
    ["tenant", "/manage-tenants", "notfound"], ["tenant", "/manage-admins", "notfound"], ["tenant", "/walls", "notfound"],
  ];
  it.each(cases)("%s on %s -> %s", (role, path, kind) => {
    expect(accessFor(me(role), path).kind).toBe(kind);
  });

  it("sends a Super Admin who opens chat or the library to Manage Admins", () => {
    expect(accessFor(me("super_admin"), "/chat")).toEqual({ kind: "redirect", to: "/manage-admins" });
    expect(accessFor(me("super_admin"), "/library/anything")).toEqual({ kind: "redirect", to: "/manage-admins" });
  });

  it("blocks pending and suspended members everywhere except their account page", () => {
    for (const state of ["pending_approval", "suspended", "rejected", "removed"] as const) {
      expect(accessFor(me("tenant", { state }), "/chat").kind).toBe("blocked");
      expect(accessFor(me("admin", { state }), "/manage-tenants").kind).toBe("blocked");
      expect(accessFor(me("tenant", { state }), "/account").kind).toBe("allow");
    }
    expect(accessFor(me("admin", { org_state: "frozen" }), "/chat").kind).toBe("blocked");
  });

  it("unknown routes are 404 and a principal-less visitor goes to onboarding", () => {
    expect(accessFor(me("admin"), "/nope").kind).toBe("notfound");
    expect(accessFor(null, "/chat")).toEqual({ kind: "redirect", to: "/onboarding" });
  });

  it("home pages and navigation show only what a role may open", () => {
    expect(homeFor(me("super_admin"))).toBe("/manage-admins");
    expect(homeFor(me("tenant"))).toBe("/chat");
    expect(homeFor(me("admin", { state: "pending_approval" }))).toBe("/onboarding");
    for (const role of ["super_admin", "admin", "tenant"] as const) {
      for (const item of NAV.filter((n) => n.roles.includes(role))) {
        expect(accessFor(me(role), item.href).kind, `${role} nav ${item.href}`).not.toBe("notfound");
      }
    }
  });
});

describe("content security policy (G8.6 helper half)", () => {
  const csp = buildCsp({ nonce: "abc123", isDev: false, uploadOrigin: "https://s3.example.com" });
  const directive = (name: string) => csp.split("; ").find((d) => d.startsWith(name + " "));

  it("uses a per-request nonce with strict-dynamic and no inline or eval scripts", () => {
    const scripts = directive("script-src") ?? "";
    expect(scripts).toContain("'nonce-abc123'");
    expect(scripts).toContain("'strict-dynamic'");
    expect(scripts).not.toContain("unsafe-inline");
    expect(scripts).not.toContain("unsafe-eval");
  });

  it("forbids framing, plugins and base-tag injection, and upgrades insecure requests", () => {
    expect(directive("frame-ancestors")).toBe("frame-ancestors 'none'");
    expect(directive("object-src")).toBe("object-src 'none'");
    expect(directive("base-uri")).toBe("base-uri 'none'");
    expect(csp).toContain("upgrade-insecure-requests");
  });

  it("lets the browser connect only to this origin and the upload origin", () => {
    expect(directive("connect-src")).toBe("connect-src 'self' https://s3.example.com");
    expect(buildCsp({ nonce: "n", isDev: false })).toContain("connect-src 'self'");
  });

  it("allows eval only in development", () => {
    expect(buildCsp({ nonce: "n", isDev: true })).toContain("'unsafe-eval'");
    expect(buildCsp({ nonce: "n", isDev: false })).not.toContain("'unsafe-eval'");
  });

  it("generates a different unguessable nonce each time", () => {
    const seen = new Set(Array.from({ length: 200 }, () => newNonce()));
    expect(seen.size).toBe(200);
    expect([...seen].every((n) => /^[A-Za-z0-9+/]{22}==$/.test(n))).toBe(true);
  });
});
