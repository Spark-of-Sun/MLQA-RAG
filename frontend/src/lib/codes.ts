// Client-side check of join codes (blueprint 7.6): Crockford Base32 with a Luhn mod-32 check character, so a typo
// is caught before anything is sent. The server re-validates everything.
const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function normalizeCode(raw: string): string {
  return raw
    .toUpperCase()
    .replace(/[\s_-]/g, "")
    .replace(/O/g, "0")
    .replace(/[IL]/g, "1");
}

export function formatCode(raw: string): string {
  const code = normalizeCode(raw).slice(0, 64);
  return code.match(/.{1,8}/g)?.join("-") ?? "";
}

export function luhnValid(code: string): boolean {
  const n = ALPHABET.length;
  let factor = 1;
  let sum = 0;
  for (let i = code.length - 1; i >= 0; i--) {
    const value = ALPHABET.indexOf(code.charAt(i));
    if (value < 0) return false;
    const addend = factor * value;
    factor = factor === 1 ? 2 : 1;
    sum += Math.floor(addend / n) + (addend % n);
  }
  return sum % n === 0;
}

export function codeProblem(raw: string, length: 32 | 64): string | null {
  const code = normalizeCode(raw);
  if (!code) return null;
  if (code.length < length) return `${length - code.length} more character(s) needed.`;
  if (code.length > length) return `This code is ${length} characters long.`;
  if (!luhnValid(code)) return "The check character does not match. Please check for a typo.";
  return null;
}
