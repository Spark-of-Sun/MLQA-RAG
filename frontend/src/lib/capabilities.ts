/**
 * User roles, route permissions, and capability definitions.
 * Implements Master System Design §17.1.
 */

export type UserRole =
  | "super_admin"
  | "admin"
  | "legal_reviewer"
  | "medical_reviewer"
  | "member"
  | "auditor"
  | "operator"
  | "pending"
  | "suspended";

export interface UserPrincipal {
  userId: string;
  orgId: string;
  workspaceId?: string;
  role: UserRole;
  email: string;
  displayName: string;
  capabilities: string[];
}

export function isTenantRole(role: UserRole): boolean {
  return [
    "legal_reviewer",
    "medical_reviewer",
    "member",
    "auditor",
  ].includes(role);
}

export function canAccessRoute(role: UserRole, pathname: string): boolean {
  if (role === "pending" || role === "suspended") {
    return pathname.startsWith("/onboarding") || pathname === "/";
  }

  // Super Admin routes
  if (pathname.startsWith("/manage-admins") || pathname.startsWith("/governance")) {
    return role === "super_admin";
  }

  // Workspace Admin routes
  if (
    pathname.startsWith("/manage-tenants") ||
    pathname.startsWith("/walls") ||
    pathname.startsWith("/review")
  ) {
    return role === "admin";
  }

  // Application routes (Chat, Library)
  if (pathname.startsWith("/chat") || pathname.startsWith("/library")) {
    return role === "admin" || isTenantRole(role);
  }

  // Audit route is accessible by all active roles (content filtered server-side)
  if (pathname.startsWith("/audit")) {
    return role === "super_admin" || role === "admin" || isTenantRole(role);
  }

  // Account and onboarding
  if (pathname.startsWith("/account") || pathname.startsWith("/onboarding")) {
    return true;
  }

  return true;
}

export function getHomeRouteForRole(role: UserRole): string {
  switch (role) {
    case "super_admin":
      return "/manage-admins";
    case "admin":
      return "/chat";
    case "legal_reviewer":
    case "medical_reviewer":
    case "member":
    case "auditor":
    case "operator":
      return "/chat";
    case "pending":
    case "suspended":
    default:
      return "/onboarding";
  }
}
