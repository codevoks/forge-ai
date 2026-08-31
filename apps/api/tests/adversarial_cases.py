from dataclasses import dataclass


@dataclass(frozen=True)
class AdversarialUrlCase:
    url: str
    expected_code: str
    reason: str


SSRF_DENIAL_CASES = (
    AdversarialUrlCase(
        url="http://example.com/callback",
        expected_code="network_scheme_denied",
        reason="plain HTTP is not accepted for tool egress",
    ),
    AdversarialUrlCase(
        url="https://localhost/admin",
        expected_code="network_private_host_denied",
        reason="loopback hostname must not be reachable from tool inputs",
    ),
    AdversarialUrlCase(
        url="https://127.0.0.1/admin",
        expected_code="network_private_address_denied",
        reason="loopback IP must not be reachable from tool inputs",
    ),
    AdversarialUrlCase(
        url="https://169.254.169.254/latest/meta-data",
        expected_code="network_private_address_denied",
        reason="link-local cloud metadata address must be denied",
    ),
    AdversarialUrlCase(
        url="https://10.0.0.4/internal",
        expected_code="network_private_address_denied",
        reason="private RFC1918 address must be denied",
    ),
)
