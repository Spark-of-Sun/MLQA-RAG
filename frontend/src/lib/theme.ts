/** The saved theme choice. Shared by the server (app/layout.tsx) and the switch (components/theme-switch.tsx). */
export const THEME_COOKIE = "cyte-theme";

export type Theme = "light" | "dark";

export function parseTheme(value: string | undefined): Theme | null {
  return value === "light" || value === "dark" ? value : null;
}
