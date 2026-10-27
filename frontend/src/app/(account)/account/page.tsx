"use client";

import { Key, ShieldCheck, Smartphone, LogOut, CheckCircle } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export default function AccountPage() {
  const authenticators = [
    {
      id: "auth-1",
      name: "YubiKey 5C NFC (Hardware FIDO2)",
      type: "passkey",
      addedAt: "2026-09-15",
      isPrimary: true,
    },
    {
      id: "auth-2",
      name: "Apple Touch ID / Passkey",
      type: "passkey",
      addedAt: "2026-10-01",
      isPrimary: false,
    },
  ];

  const sessions = [
    {
      id: "sess-curr",
      device: "Current Session (Linux / Chrome)",
      ip: "10.0.1.42 (VPC Ingress)",
      lastActive: "Active now",
      isCurrent: true,
    },
    {
      id: "sess-other",
      device: "macOS Safari (Workstation)",
      ip: "10.0.1.88 (VPC Ingress)",
      lastActive: "Yesterday at 18:24",
      isCurrent: false,
    },
  ];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Account & Security</h1>
        <p className="mt-1 text-sm text-slate-500">
          Manage hardware FIDO2 passkeys, backup authenticators, and inspect active sessions.
        </p>
      </div>

      {/* Authenticators Section */}
      <Card title="Registered Hardware Authenticators (FIDO2 / WebAuthn)" description="Master §8 mandates hardware passkeys for all reviewer and administrative roles.">
        <div className="space-y-3 mt-4">
          {authenticators.map((auth) => (
            <div key={auth.id} className="flex items-center justify-between p-4 bg-slate-50 rounded-lg border border-slate-200">
              <div className="flex items-center gap-3">
                <Key className="h-5 w-5 text-slate-600" />
                <div>
                  <p className="text-sm font-semibold text-slate-900">{auth.name}</p>
                  <p className="text-xs text-slate-500 mt-0.5">Enrolled: {auth.addedAt}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {auth.isPrimary && <Badge variant="success">PRIMARY</Badge>}
                <Badge variant="neutral">WEBAUTHN</Badge>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Active Sessions */}
      <Card title="Active Authenticated Sessions" description="Opaque httpOnly session tokens residing on the server.">
        <div className="space-y-3 mt-4">
          {sessions.map((sess) => (
            <div key={sess.id} className="flex items-center justify-between p-4 bg-slate-50 rounded-lg border border-slate-200">
              <div className="flex items-center gap-3">
                <Smartphone className="h-5 w-5 text-slate-600" />
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-slate-900">{sess.device}</p>
                    {sess.isCurrent && <Badge variant="info">CURRENT</Badge>}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5 font-mono">{sess.ip} • {sess.lastActive}</p>
                </div>
              </div>

              {!sess.isCurrent && (
                <Button variant="outline" size="sm">
                  <LogOut className="h-3.5 w-3.5 mr-1" />
                  <span>Revoke</span>
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
