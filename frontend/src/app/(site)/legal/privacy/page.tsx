import type { Metadata } from "next";

import { LegalDoc } from "@/components/site/legal";
import { pageMeta } from "@/components/site/seo";
import { BRAND, COMPANY, CONTACT_EMAIL } from "@/lib/format";

export const metadata: Metadata = pageMeta("Privacy notice", `How ${COMPANY} handles personal data on this website and in ${BRAND}.`, "/legal/privacy");

export default function PrivacyPage() {
  return (
    <LegalDoc title="Privacy notice" intro={`How ${COMPANY} handles personal data on this website and in ${BRAND}.`}>
      <h2>Who we are</h2>
      <p>
        {BRAND} is made by {COMPANY}. For anything in this notice, write to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>

      <h2>On this website</h2>
      <ul>
        <li>We do not use analytics, advertising or tracking cookies, and we load no third-party scripts.</li>
        <li>The contact form prepares an email in your own mail app. Our server does not store what you type.</li>
        <li>When you email us, we keep your message and address to answer you and to follow up on your request.</li>
        <li>Our servers may keep technical logs (such as the address that made a request, and when) to run and secure the service.</li>
      </ul>

      <h2>In the product</h2>
      <p>When your organization uses {BRAND}, we process the data needed to provide it:</p>
      <ul>
        <li>Account details from sign-in (name and email), and profile details you choose to add (job title, department, phone).</li>
        <li>Documents you upload, the passages made from them, your chats, and the answers {BRAND} gives.</li>
        <li>An audit trail of actions such as joins, approvals, uploads, shares and answers. Questions and answers are recorded there as hashes, not as text.</li>
        <li>Usage counts (documents, shares, questions and approximate tokens) that admins can see for their workspace.</li>
      </ul>

      <h2>Who else processes data</h2>
      <ul>
        <li><strong>Auth0</strong> handles sign-in.</li>
        <li><strong>Google</strong> receives document text to make it searchable.</li>
        <li><strong>The configured AI model provider</strong> receives the passages behind each question to draft the answer.</li>
      </ul>
      <p>
        During early access, please talk to us about hosting and data agreements before you upload client or patient
        records.
      </p>

      <h2>Who can see your content</h2>
      <p>
        Your uploads are private until you share them. Chats are never visible to your admin or to the organization owner.
        Access is enforced in the database itself; see the <a href="/security">Security</a> page for details.
      </p>

      <h2>Keeping and deleting data</h2>
      <p>
        You can delete your own documents and chats. Suspending a person stops their access but does not delete their
        data. Audit records cannot be edited or removed. Ask us about deleting an organization&apos;s data.
      </p>

      <h2>Your rights</h2>
      <p>
        Depending on where you live, you may have the right to access, correct, delete or export your personal data, and
        to object to some processing. Write to us and we will respond. If your organization provides your account, we may
        refer your request to them.
      </p>

      <h2>Changes</h2>
      <p>We will update this notice when the way we handle data changes, and show the date of the latest version here.</p>
    </LegalDoc>
  );
}
