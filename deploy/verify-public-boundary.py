"""Read-only external SEC-01 checks. Run outside the production server."""

import argparse
import http.client
import json
import socket
import ssl


def verify(host):
    results = {}

    def request(tls, method, path, headers=None):
        connection_class = http.client.HTTPSConnection if tls else http.client.HTTPConnection
        connection = connection_class(host, timeout=10)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            response.read(65536)
            return response.status, response.getheaders()
        finally:
            connection.close()

    status, headers = request(False, "GET", "/")
    results["http_redirect"] = (
        status in (301, 302, 307, 308) and dict(headers).get("Location") == f"https://{host}/"
    )
    status, _ = request(False, "POST", "/api/auth/login")
    results["plaintext_login_rejected"] = status in (400, 403, 404, 405, 426)
    status, headers = request(True, "GET", "/login")
    lowered = [(key.lower(), value) for key, value in headers]
    results["valid_tls_and_ui"] = status == 200
    policies = [value for key, value in lowered if key == "content-security-policy"]
    results["single_enforced_csp"] = len(policies) == 1 and all(
        directive in policies[0]
        for directive in ("object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'")
    )
    results["frame_denied"] = dict(lowered).get("x-frame-options") == "DENY"
    results["hsts_present"] = "strict-transport-security" in dict(lowered)
    status, _ = request(True, "GET", "/", {"Host": "untrusted.invalid"})
    results["unknown_host_rejected"] = status in (400, 403, 421)

    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    for address in addresses:
        for port in (8000, 5432):
            try:
                with socket.create_connection((address, port), timeout=3):
                    closed = False
            except (TimeoutError, ConnectionRefusedError):
                closed = True
            except OSError as error:
                # No local IPv6 route is not evidence of remote port isolation.
                results[f"{address}:{port}"] = f"inconclusive: {type(error).__name__}"
                continue
            results[f"{address}:{port}"] = closed
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Public DNS hostname, without scheme or path")
    args = parser.parse_args()
    try:
        evidence = verify(args.host)
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        raise SystemExit(f"Verification could not complete: {type(error).__name__}") from None
    print(json.dumps(evidence, indent=2))
    raise SystemExit(0 if all(value is True for value in evidence.values()) else 1)
