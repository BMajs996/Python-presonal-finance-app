"""Production entry point for the single-host reverse-proxy deployment."""

import uvicorn

from .core.config import Settings, settings


def server_options(config: Settings) -> dict:
    if config.environment != "production":
        raise ValueError("Production launcher requires ENVIRONMENT=production")
    # Revalidate even if settings were constructed or mutated programmatically.
    checked = Settings.model_validate(config.model_dump())
    return {
        "host": "127.0.0.1",
        "port": checked.app_port,
        "reload": False,
        "workers": 1,
        "proxy_headers": True,
        "forwarded_allow_ips": ",".join(checked.trusted_proxy_list),
        "access_log": False,
        "server_header": False,
    }


def main():
    uvicorn.run("backend.app.main:app", **server_options(settings))


if __name__ == "__main__":
    main()
