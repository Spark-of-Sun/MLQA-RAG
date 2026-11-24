import type { Metadata } from "next";

import { GovernanceCenter } from "@/components/governance/governance-center";

export const metadata: Metadata = { title: "Governance" };

export default function OrganizationGovernancePage() {
  return <GovernanceCenter title="Organization governance" />;
}
