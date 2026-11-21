import type { MetadataRoute } from "next";

import { BRAND, COMPANY } from "@/lib/format";

// Served at /manifest.webmanifest; replaces the supplied site.webmanifest, whose name fields were empty.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${BRAND} by ${COMPANY}`,
    short_name: BRAND,
    description: "Verified, cited answers from legal and medical documents.",
    start_url: "/home",
    display: "standalone",
    theme_color: "#ffffff",
    background_color: "#ffffff",
    icons: [
      { src: "/android-chrome-192x192.png", sizes: "192x192", type: "image/png" },
      { src: "/android-chrome-512x512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
