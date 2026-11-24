import type { Me } from "@/lib/types";

/**
 * Feature flags from contracts/features.toml, as reported by the gateway in `/v1/me` (`features`: the enabled ones).
 * Hiding a screen is convenience, not control: the gateway answers 404 for a disabled feature's routes.
 *
 * The frozen MVP-only features (DEV-21, pending Q-04) are off until that question is answered.
 */
export type Feature =
  | "chats"
  | "profiles"
  | "named_shares"
  | "workspace_visibility"
  | "usage_counts"
  | "public_site"
  | "llm_reranker"
  | "quota_rotation"
  | "sentence_streaming"
  | "matters_walls_tiers"
  | "governance_requests";

export type Features = ReadonlySet<string>;

export function featuresOf(me: Pick<Me, "features"> | null | undefined): Features {
  return new Set(me?.features ?? []);
}

export function hasFeature(me: Pick<Me, "features"> | null | undefined, name: Feature): boolean {
  return featuresOf(me).has(name);
}
