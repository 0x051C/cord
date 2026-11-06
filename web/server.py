import asyncio
from typing import Optional

from application.configuration_handling import resolve_path
from application.logging_setup import configure_logging, validation_logger
from web import create_app
from web.auth import is_loopback


def bind_address(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def serve(settings, host: Optional[str] = None, port: Optional[int] = None) -> None:
    from hypercorn.asyncio import serve as hypercorn_serve
    from hypercorn.config import Config

    host = host or str(settings.get("web_host", "127.0.0.1"))
    port = int(port or settings.get("web_port", 8000))
    if str(settings.get("web_auth", "kerberos")).lower() == "none" and not is_loopback(host):
        raise SystemExit(
            f"Refusing to serve without authentication on {host}: web_auth = 'none' is only allowed on "
            "a loopback address (127.0.0.1 / ::1 / localhost)."
        )

    configure_logging(resolve_path(settings.get("log_dir", ".")))
    try:
        app = create_app(settings)
    except ValueError as e:  # incomplete web_* settings
        raise SystemExit(f"Cannot start the dashboard: {e}")

    config = Config()
    config.bind = [bind_address(host, port)]
    config.accesslog = "-"
    certfile, keyfile = settings.get("web_tls_certfile"), settings.get("web_tls_keyfile")
    if certfile:
        config.certfile, config.keyfile = str(certfile), str(keyfile)
    scheme = "https" if certfile else "http"
    shown_host = "localhost" if is_loopback(host) else settings.get("web_kerberos_hostname") or host
    validation_logger.info(f"web: dashboard on {scheme}://{shown_host}:{port}/ (Ctrl+C to stop)")
    asyncio.run(hypercorn_serve(app, config))
