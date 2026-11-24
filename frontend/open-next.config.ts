// OpenNext adapter for Cloudflare Workers (docs/deploy.md). Every page is rendered per request (sessions, CSP
// nonces), so no incremental cache is configured.
import { defineCloudflareConfig } from "@opennextjs/cloudflare";

export default defineCloudflareConfig({});
