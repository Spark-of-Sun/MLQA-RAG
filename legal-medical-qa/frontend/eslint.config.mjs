import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // The browser may call the Gateway only through lib/api-client (doc 4.7); route handlers hold the tokens.
    files: ["src/app/**/*.tsx", "src/components/**/*.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.name='fetch'][arguments.0.value=/^https?:/]",
          message: "Do not call another origin from a component; use lib/api-client.",
        },
      ],
    },
  },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts"]),
]);
