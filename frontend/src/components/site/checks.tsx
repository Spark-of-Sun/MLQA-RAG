/**
 * The ten checks every drafted sentence must pass before it is shown. Shared by the products index (`/product`)
 * and each product's own page (`/products/legal`, `/products/medical`), since the verification engine is the same
 * for both products.
 */
export const VERIFICATION_CHECKS: [string, string][] = [
  ["Citation format", "The citation points to a real source of this answer."],
  ["Source was retrieved", "The answer cites only passages found for this question."],
  ["Source unchanged", "The passage did not change between search and answer."],
  ["Sentence is cited", "Every sentence that states a fact has a citation."],
  ["Quote found in source", "The supporting quote appears word for word in the passage."],
  ["Numbers and dates match", "Every number, date, amount and dosage appears in the passage."],
  ["Wording supported", "The sentence's key terms come from the passage."],
  ["Source entails the claim", "A second, stricter review confirms the passage supports the claim."],
  ["Refusal wording", "A “does not address” reply is exact and stands alone."],
  ["Resolves to page and section", "The citation leads to a real place in the document."],
];

/** The ten-checks grid, as a numbered list. */
export function VerificationChecks() {
  return (
    <ol className="grid border-t border-l border-ink-200 sm:grid-cols-2 lg:grid-cols-5">
      {VERIFICATION_CHECKS.map(([title, body], i) => (
        <li key={title} className="border-r border-b border-ink-200 p-5">
          <span className="font-mono text-xs text-ink-400">{String(i + 1).padStart(2, "0")}</span>
          <h3 className="mt-4 text-sm font-semibold text-ink-950">{title}</h3>
          <p className="mt-1.5 text-xs leading-5 text-ink-600">{body}</p>
        </li>
      ))}
    </ol>
  );
}
