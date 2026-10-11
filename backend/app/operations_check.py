"""Credential-free health check for a timer or external monitoring service."""

import argparse
import http.client
import json
from urllib.parse import urlsplit

PROBES = {"liveness": "/api/health", "readiness": "/api/health/ready", "worker": "/api/health/worker"}


def origin(value: str) -> str:
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid monitoring origin") from None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise argparse.ArgumentTypeError("Use an HTTP(S) origin without credentials or paths")
    if parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise argparse.ArgumentTypeError("Public monitoring requires HTTPS")
    return value.rstrip("/")


def check(base: str) -> dict[str, str]:
    parts = urlsplit(origin(base))
    results = {}
    for name, path in PROBES.items():
        connection_class = (
            http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_class(parts.hostname or "", parts.port, timeout=5)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = json.loads(response.read(256))
            status = body.get("status") if isinstance(body, dict) else None
            acceptable = {"ok", "starting"} if name == "worker" else {"ok"}
            results[name] = (
                status
                if response.status == 200 and isinstance(status, str) and status in acceptable
                else "unavailable"
            )
        except (http.client.HTTPException, OSError, ValueError):
            results[name] = "unavailable"
        finally:
            connection.close()
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=origin, required=True)
    results = check(parser.parse_args(argv).url)
    print(json.dumps(results, sort_keys=True))
    return 1 if "unavailable" in results.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
