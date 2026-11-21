"""Security properties of the generated Kubernetes manifests (no cluster here, so the YAML itself is the test)."""

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.stage11]
BASE = Path(__file__).resolve().parents[2] / "infra" / "k8s" / "base"


def load(name: str) -> list[dict]:
    return list(yaml.safe_load_all((BASE / name).read_text()))


@pytest.fixture(scope="module")
def deployments() -> dict[str, dict]:
    out = {}
    for f in BASE.glob("*.yaml"):
        for doc in yaml.safe_load_all(f.read_text()):
            if doc and doc.get("kind") == "Deployment":
                out[doc["metadata"]["name"]] = doc
    return out


@pytest.fixture(scope="module")
def policies() -> dict[str, dict]:
    return {d["metadata"]["name"]: d for d in load("network-policies.yaml")}


def test_all_eight_services_have_a_deployment(deployments: dict[str, dict]) -> None:
    assert set(deployments) == {
        "gateway",
        "identity",
        "ingestion",
        "retrieval",
        "generation",
        "citation-validator",
        "audit",
        "frontend",
    }


def test_every_container_is_non_root_read_only_and_unprivileged(
    deployments: dict[str, dict],
) -> None:
    for name, d in deployments.items():
        pod = d["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True, name
        assert pod["automountServiceAccountToken"] is False, name
        assert not pod.get("hostNetwork"), name
        assert not pod.get("hostPID"), name
        for c in pod["containers"]:
            sc = c["securityContext"]
            assert sc["readOnlyRootFilesystem"] is True, name
            assert sc["allowPrivilegeEscalation"] is False, name
            assert sc["capabilities"]["drop"] == ["ALL"], name
            assert "memory" in c["resources"]["limits"], name
            assert "readinessProbe" in c, name
            assert "livenessProbe" in c, name


def test_rollouts_never_drop_below_capacity(deployments: dict[str, dict]) -> None:
    for name, d in deployments.items():
        assert d["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0, name
        assert d["spec"]["replicas"] >= 2, name


def test_the_namespace_enforces_the_restricted_pod_security_standard() -> None:
    ns = load("namespace.yaml")[0]
    assert ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_everything_is_denied_by_default(policies: dict[str, dict]) -> None:
    deny = policies["default-deny"]["spec"]
    assert deny["podSelector"] == {}
    assert set(deny["policyTypes"]) == {"Ingress", "Egress"}


def _callers(policy: dict) -> set[str]:
    out = set()
    for rule in policy["spec"].get("ingress", []):
        for peer in rule.get("from", []):
            out.add(peer["podSelector"]["matchLabels"]["app.kubernetes.io/name"])
    return out


def test_only_the_frontend_is_reachable_from_outside_and_only_the_gateway_reaches_the_services(
    policies: dict[str, dict],
) -> None:
    assert policies["frontend-allow"]["spec"]["ingress"] == [
        {"ports": [{"port": 3000, "protocol": "TCP"}]}
    ]
    assert _callers(policies["gateway-allow"]) == {"frontend"}
    for svc in ("identity", "ingestion", "retrieval", "generation", "citation-validator", "audit"):
        assert _callers(policies[f"{svc}-allow"]) == {"gateway"}, svc


def _egress_peers(policy: dict) -> set[str]:
    return {
        p["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
        for rule in policy["spec"].get("egress", [])
        for p in rule.get("to", [])
        if "podSelector" in p
    }


def test_only_retrieval_and_ingestion_can_reach_qdrant(policies: dict[str, dict]) -> None:
    reaching = {
        name.removesuffix("-allow")
        for name, p in policies.items()
        if name.endswith("-allow") and "qdrant" in _egress_peers(p)
    }
    assert reaching == {"ingestion", "retrieval"}


def test_the_gateway_is_the_only_service_that_calls_the_others(policies: dict[str, dict]) -> None:
    for name, p in policies.items():
        if name.endswith("-allow") and name != "gateway-allow":
            others = _egress_peers(p) - {"qdrant"}
            assert others <= ({"gateway"} if name == "frontend-allow" else set()), name


def test_the_validator_and_retrieval_have_no_internet_egress_and_nobody_reaches_instance_metadata(
    policies: dict[str, dict],
) -> None:
    def internet(p: dict) -> bool:
        return any(
            peer.get("ipBlock", {}).get("cidr") == "0.0.0.0/0"
            for r in p["spec"]["egress"]
            for peer in r.get("to", [])
        )

    assert not internet(policies["citation-validator-allow"])
    assert not internet(policies["retrieval-allow"])
    for name, p in policies.items():
        for rule in p["spec"].get("egress", []):
            for peer in rule.get("to", []):
                if peer.get("ipBlock", {}).get("cidr") == "0.0.0.0/0":
                    assert "169.254.169.254/32" in peer["ipBlock"]["except"], name


def test_the_ingress_is_https_only_with_a_tls13_policy() -> None:
    ing = load("ingress.yaml")[0]
    ann = ing["metadata"]["annotations"]
    assert ann["alb.ingress.kubernetes.io/listen-ports"] == '[{"HTTPS":443}]'
    assert "TLS13" in ann["alb.ingress.kubernetes.io/ssl-policy"]
    assert ing["spec"]["rules"][0]["host"] == "onekami.site"
