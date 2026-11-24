import type { Metadata } from "next";
import Link from "next/link";

import { LegalDoc } from "@/components/site/legal";
import { pageMeta } from "@/components/site/seo";
import { BRAND, COMPANY, CONTACT_EMAIL } from "@/lib/format";

export const metadata: Metadata = pageMeta("Terms of use", `The terms for using this website and ${BRAND}.`, "/legal/terms");

export default function TermsPage() {
  return (
    <LegalDoc title="Terms of use" intro={`The terms for using this website and ${BRAND}. Organizations on a pilot or plan may also have a written agreement with ${COMPANY}; where it differs, that agreement applies.`}>
      <h2>The service</h2>
      <p>
        {BRAND} answers questions about documents your organization uploads, with citations to the passages it used. It is
        in early access: features may change, and some designed features are not built yet (listed in the{" "}
        <Link href="/docs/roadmap">documentation</Link>).
      </p>

      <h2>Not legal or medical advice</h2>
      <p>
        {BRAND} reports what your documents say. It does not give legal or medical advice, and its answers are not a
        substitute for the judgement of a qualified professional. Check the cited passage before you rely on an answer.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>Keep your sign-in details to yourself, and use invite and organization codes only as intended.</li>
        <li>Your organization&apos;s admins decide who joins, and can suspend access.</li>
      </ul>

      <h2>Your content</h2>
      <ul>
        <li>You keep all rights in the documents you upload and the questions you ask.</li>
        <li>You give us permission to process your content only to provide the service to your organization.</li>
        <li>Upload only documents you are allowed to use, and agree hosting and data terms with us before uploading client or patient records.</li>
      </ul>

      <h2>Acceptable use</h2>
      <ul>
        <li>Do not try to reach other organizations&apos;, workspaces&apos; or people&apos;s data.</li>
        <li>Do not disrupt the service, get around its limits, or probe it for weaknesses except through responsible disclosure to {CONTACT_EMAIL}.</li>
      </ul>

      <h2>Availability and liability</h2>
      <p>
        We work to keep {BRAND} available and correct, but during early access it is provided as it is. The limits of our
        liability will be set out here once reviewed by counsel, and in any written agreement with your organization.
      </p>

      <h2>Contact</h2>
      <p>
        Questions about these terms: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    </LegalDoc>
  );
}
