/**
 * Gateway API client wrapper for Next.js BFF handlers.
 * Implements Master System Design §17.3.
 */

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8000";

export interface GatewayClientOptions {
  accessToken?: string;
  contextToken?: string;
}

export class GatewayClient {
  private baseUrl: string;

  constructor(baseUrl: string = GATEWAY_URL) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async fetch(
    path: string,
    options: RequestInit = {},
    clientOptions: GatewayClientOptions = {},
  ): Promise<Response> {
    const headers = new Headers(options.headers);
    headers.set("Content-Type", "application/json");

    if (clientOptions.accessToken) {
      headers.set("Authorization", `Bearer ${clientOptions.accessToken}`);
    }
    if (clientOptions.contextToken) {
      headers.set("X-Context-Token", clientOptions.contextToken);
    }

    const url = `${this.baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
    return globalThis.fetch(url, {
      ...options,
      headers,
    });
  }

  async getHealth(): Promise<{ status: string }> {
    const res = await this.fetch("/healthz");
    if (!res.ok) {
      throw new Error(`Health check failed with status: ${res.status}`);
    }
    return res.json();
  }
}

export const gatewayClient = new GatewayClient();
