// ESLint flat config (blueprint 19.3, G8.8): typescript-eslint strict type-checked plus the Next.js rules, zero
// warnings allowed. The browser reaches the gateway only through the BFF client (4.7).
import nextPlugin from "@next/eslint-plugin-next";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: [".next/**", "node_modules/**", "src/lib/api-schema.d.ts", "next-env.d.ts"] },
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    plugins: { "@next/next": nextPlugin },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      "no-restricted-globals": ["error", { name: "localStorage", message: "No tokens or session data in browser storage (G8.5)." },
        { name: "sessionStorage", message: "No tokens or session data in browser storage (G8.5)." }],
      "no-restricted-syntax": ["error", {
        selector: "CallExpression[callee.name='fetch'] > Literal[value=/^https?:/]",
        message: "Call the gateway only through the BFF (/api/backend) via lib/api-client or lib/answer-stream.",
      }],
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
    },
  },
);
