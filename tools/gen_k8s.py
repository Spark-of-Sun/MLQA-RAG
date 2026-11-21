"""Generate the Kubernetes base manifests (doc 4.7, 18): one Deployment, Service and ServiceAccount per
service, a default-deny NetworkPolicy plus the allow rules that encode who may call whom, and the
frontend Ingress. Run:  uv run python tools/gen_k8s.py

The output is committed (infra/k8s/base) so a reviewer reads the real YAML; tests assert its security
properties. It has NOT been applied to a cluster in the authoring sandbox (no cluster, no kubectl).
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "infra" / "k8s" / "base"
NS = "lmqa"
IMAGE = "REGISTRY/lmqa-ENV/{name}:TAG"  # replaced by the overlay (kustomize images)
# Managed PostgreSQL (through the pooler) and Valkey live in these private subnets: set the real CIDR in the
# overlay. It is deliberately NOT the whole VPC range, so it never covers the Qdrant pods.
DATA_CIDR = "10.20.0.0/20"

# name, port, public path prefix for probes, who may call it (network policy), egress it needs
SERVICES = {
    "gateway": {
        "port": 8000,
        "health": "/v1/health",
        "from": ["frontend"],
        "to": ["identity", "ingestion", "retrieval", "generation", "citation-validator", "audit"],
        "internet": True,
    },
    "identity": {
        "port": 8005,
        "health": "/internal/v1/health",
        "from": ["gateway"],
        "to": [],
        "internet": True,
    },
    "ingestion": {
        "port": 8001,
        "health": "/internal/v1/health",
        "from": ["gateway"],
        "to": [],
        "internet": True,
        "vector": True,
    },
    "retrieval": {
        "port": 8002,
        "health": "/internal/v1/health",
        "from": ["gateway"],
        "to": [],
        "internet": False,
        "vector": True,
    },
    "generation": {
        "port": 8003,
        "health": "/internal/v1/health",
        "from": ["gateway"],
        "to": [],
        "internet": True,
    },
    "citation-validator": {
        "port": 8004,
        "health": "/internal/v1/health",
        "from": ["gateway"],
        "to": [],
        "internet": False,
    },
    "audit": {
        "port": 8007,
        "health": "/internal/v1/health",
        "from": ["gateway"],
        "to": [],
        "internet": True,
    },
    "frontend": {
        "port": 3000,
        "health": "/api/health",
        "from": [],
        "to": ["gateway"],
        "internet": True,
        "public": True,
    },
}
MEMORY = {
    "ingestion": "3Gi",
    "retrieval": "3Gi",
    "citation-validator": "3Gi",
    "generation": "1Gi",
    "frontend": "512Mi",
}


def labels(name: str) -> dict[str, str]:
    return {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": "lmqa"}


def deployment(name: str, spec: dict) -> dict:
    sa = name
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": NS, "labels": labels(name)},
        "spec": {
            "replicas": 2,
            "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
            "strategy": {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
            },
            "template": {
                "metadata": {"labels": labels(name)},
                "spec": {
                    "serviceAccountName": sa,
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "topologySpreadConstraints": [
                        {
                            "maxSkew": 1,
                            "topologyKey": "topology.kubernetes.io/zone",
                            "whenUnsatisfiable": "ScheduleAnyway",
                            "labelSelector": {"matchLabels": {"app.kubernetes.io/name": name}},
                        }
                    ],
                    "containers": [
                        {
                            "name": name,
                            "image": IMAGE.format(name=name),
                            "imagePullPolicy": "IfNotPresent",
                            "ports": [{"containerPort": spec["port"], "name": "http"}],
                            "envFrom": [
                                {"configMapRef": {"name": "lmqa-config"}},
                                {"secretRef": {"name": f"lmqa-{name}"}},
                            ],
                            "readinessProbe": {
                                "httpGet": {"path": spec["health"], "port": "http"},
                                "periodSeconds": 5,
                                "failureThreshold": 6,
                            },
                            "livenessProbe": {
                                "httpGet": {"path": spec["health"], "port": "http"},
                                "initialDelaySeconds": 30,
                                "periodSeconds": 15,
                            },
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "256Mi"},
                                "limits": {"memory": MEMORY.get(name, "768Mi")},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],  # noqa: S108 - an in-memory emptyDir mounted at /tmp, not a host temp file
                        }
                    ],
                    "volumes": [
                        {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}}
                    ],
                },
            },
        },
    }


def service(name: str, spec: dict) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": NS, "labels": labels(name)},
        "spec": {
            "selector": {"app.kubernetes.io/name": name},
            "ports": [{"name": "http", "port": spec["port"], "targetPort": "http"}],
        },
    }


def account(name: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": name, "namespace": NS, "labels": labels(name)},
    }


def peer(name: str) -> dict:
    return {"podSelector": {"matchLabels": {"app.kubernetes.io/name": name}}}


def policies() -> list[dict]:
    out: list[dict] = [
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "default-deny", "namespace": NS},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "allow-dns", "namespace": NS},
            "spec": {
                "podSelector": {},
                "policyTypes": ["Egress"],
                "egress": [
                    {"ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}
                ],
            },
        },
    ]
    for name, spec in SERVICES.items():
        ingress = (
            [
                {
                    "from": [peer(p) for p in spec["from"]],
                    "ports": [{"port": spec["port"], "protocol": "TCP"}],
                }
            ]
            if spec["from"]
            else []
        )
        if spec.get("public"):  # only the frontend is reachable from the load balancer
            ingress = [{"ports": [{"port": spec["port"], "protocol": "TCP"}]}]
        egress: list[dict] = []
        if spec["to"]:
            egress.append({"to": [peer(t) for t in spec["to"]]})
        egress.append(
            {
                "to": [{"ipBlock": {"cidr": DATA_CIDR}}],
                "ports": [
                    {"port": 5432, "protocol": "TCP"},
                    {"port": 6432, "protocol": "TCP"},
                    {"port": 6379, "protocol": "TCP"},
                ],
            }
        )
        if spec.get(
            "vector"
        ):  # only retrieval (read-only key) and ingestion (read-write key) may reach Qdrant (doc 4.7)
            egress.append({"to": [peer("qdrant")], "ports": [{"port": 6333, "protocol": "TCP"}]})
        if spec["internet"]:
            egress.append(
                {
                    "to": [
                        {
                            "ipBlock": {
                                "cidr": "0.0.0.0/0",
                                "except": ["10.0.0.0/8", "169.254.169.254/32"],
                            }
                        }
                    ],
                    "ports": [{"port": 443, "protocol": "TCP"}],
                }
            )
        out.append(
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": f"{name}-allow", "namespace": NS},
                "spec": {
                    "podSelector": {"matchLabels": {"app.kubernetes.io/name": name}},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": ingress,
                    "egress": egress,
                },
            }
        )
    return out


def ingress() -> dict:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": "frontend",
            "namespace": NS,
            "annotations": {
                "alb.ingress.kubernetes.io/scheme": "internet-facing",
                "alb.ingress.kubernetes.io/target-type": "ip",
                "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}]',
                "alb.ingress.kubernetes.io/ssl-policy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
                "alb.ingress.kubernetes.io/certificate-arn": "REPLACE_WITH_ACM_CERTIFICATE_ARN",
                "alb.ingress.kubernetes.io/healthcheck-path": "/api/health",
                "alb.ingress.kubernetes.io/load-balancer-attributes": "idle_timeout.timeout_seconds=300",  # SSE answers stay open
            },
        },
        "spec": {
            "ingressClassName": "alb",
            "rules": [
                {
                    "host": "onekami.site",
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {"name": "frontend", "port": {"number": 3000}}
                                },
                            }
                        ]
                    },
                }
            ],
        },
    }


def config_map() -> dict:
    data = {
        "APP_ENV": "production",
        "PRODUCT_DOMAIN": "onekami.site",
        "APP_BASE_URL": "https://onekami.site",
        "KMS_PROVIDER": "aws",
        "AWS_REGION": "us-east-1",
        "IDENTITY_URL": "http://identity:8005",
        "INGESTION_URL": "http://ingestion:8001",
        "RETRIEVAL_URL": "http://retrieval:8002",
        "GENERATION_URL": "http://generation:8003",
        "VALIDATOR_URL": "http://citation-validator:8004",
        "AUDIT_URL": "http://audit:8007",
        "API_BASE_URL": "http://gateway:8000",
        "TRUST_CLOUDFLARE": "true",
        "CONTRACTS_DIR": "/app/contracts",
        "PROMPTS_DIR": "/app/prompts",
        "ANSWER_CACHE": "off",
        "AUTH0_AUDIENCE_MAIN": "https://api.onekami.site",
        "AUTH0_AUDIENCE_ONBOARDING": "https://onboarding.onekami.site",
        "AUTH0_CLAIMS_NAMESPACE": "https://claims.onekami.site",
    }
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "lmqa-config", "namespace": NS},
        "data": data,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    docs: dict[str, list[dict]] = {
        "namespace.yaml": [
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": NS,
                    "labels": {"pod-security.kubernetes.io/enforce": "restricted"},
                },
            }
        ],
        "config.yaml": [config_map()],
        "network-policies.yaml": policies(),
        "ingress.yaml": [ingress()],
    }
    for name, spec in SERVICES.items():
        docs[f"{name}.yaml"] = [account(name), deployment(name, spec), service(name, spec)]
    for filename, items in docs.items():
        (OUT / filename).write_text(yaml.safe_dump_all(items, sort_keys=False), encoding="utf-8")
    resources = "\n".join(f"  - {f}" for f in docs)
    (OUT / "kustomization.yaml").write_text(
        f"apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n{resources}\n",
        encoding="utf-8",
    )
    print(f"wrote {len(docs)} manifests to {OUT}")


if __name__ == "__main__":
    main()
