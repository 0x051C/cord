"""Read-only monitoring dashboard (Quart + htmx + Tabulator)."""

import base64
import secrets
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from quart import Quart, Response, current_app, g, render_template, request, session
from quart.utils import run_sync
from werkzeug.exceptions import HTTPException

from application.logging_setup import validation_logger
from application.pipeline_config import PipelineConfig
from application.storage import Repository, build_repository
from web.auth import (
    SESSION_PRINCIPAL,
    AuthenticationFailed,
    Authenticator,
    build_authenticator,
    parse_negotiate_header,
)
from web.data import DepartmentCache

PUBLIC_PATHS = ("/static/", "/healthz")
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@dataclass
class WebContext:
    settings: object
    config: PipelineConfig
    authenticator: Authenticator
    environment: str
    cache: DepartmentCache = field(default_factory=DepartmentCache)
    _repository: Optional[Repository] = None
    _owns_repository: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def repository(self) -> Repository:
        with self._lock:
            if self._repository is None:
                self._repository = build_repository(self.settings)
                self._owns_repository = True
            return self._repository

    def close(self) -> None:
        with self._lock:
            if self._repository is not None and self._owns_repository:
                self._repository.close()
                self._repository = None


def state() -> WebContext:
    return current_app.extensions["cord"]


def create_app(
    settings=None,
    *,
    repository: Optional[Repository] = None,
    authenticator: Optional[Authenticator] = None,
    config: Optional[PipelineConfig] = None,
) -> Quart:
    from application.configuration_handling import ENVIRONMENT

    if settings is None:
        from application.configuration_handling import settings

    authenticator = authenticator or build_authenticator(settings)
    secret_key = settings.get("web_secret_key")
    if not secret_key:
        secret_key = secrets.token_hex(32)
        if authenticator.challenge is not None:
            validation_logger.warning(
                "web: web_secret_key is not set, sessions are lost on restart and cannot be shared between workers"
            )

    app = Quart(__name__)
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_NAME="cord_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(settings.get("web_cookie_secure", bool(settings.get("web_tls_certfile")))),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=float(settings.get("web_session_hours", 8))),
        TEMPLATES_AUTO_RELOAD=ENVIRONMENT != "production",
    )
    app.extensions["cord"] = WebContext(
        settings=settings,
        config=config or PipelineConfig.from_settings(settings),
        authenticator=authenticator,
        environment=ENVIRONMENT,
        _repository=repository,
    )

    @app.before_request
    async def authenticate():
        if request.path.startswith(PUBLIC_PATHS):
            return None
        auth = state().authenticator
        if auth.challenge is None:
            g.principal = "local"
            return None
        principal = session.get(SESSION_PRINCIPAL)
        if principal and auth.is_allowed(principal):
            g.principal = principal
            return None
        token = parse_negotiate_header(request.headers.get("Authorization"))
        if token is None:
            return await _challenge(auth.challenge)
        try:
            negotiated = await run_sync(auth.accept)(token)
        except AuthenticationFailed as e:
            validation_logger.warning(f"web: authentication failed from {request.remote_addr}: {e}")
            return await _challenge(auth.challenge, failed=True)
        if not auth.is_allowed(negotiated.principal):
            validation_logger.warning(f"web: {negotiated.principal} is not allowed to use the dashboard")
            return await render_template("denied.html", principal=negotiated.principal), 403
        session.clear()
        session[SESSION_PRINCIPAL] = negotiated.principal
        session.permanent = True
        g.principal = negotiated.principal
        g.out_token = negotiated.out_token
        validation_logger.info(f"web: {negotiated.principal} signed in")
        return None

    @app.after_request
    async def headers(response: Response) -> Response:
        out_token = g.get("out_token")
        if out_token:
            response.headers["WWW-Authenticate"] = "Negotiate " + base64.b64encode(out_token).decode()
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(Exception)
    async def failure(error: Exception):
        if isinstance(error, HTTPException):
            return error
        validation_logger.exception("web: request failed")
        return await render_template("error.html", error=error), 500

    @app.context_processor
    def globals_():
        return {"environment": state().environment, "principal": g.get("principal")}

    @app.after_serving
    async def shutdown():
        state().close()

    from web.views import blueprint

    app.register_blueprint(blueprint)
    return app


async def _challenge(scheme: str, failed: bool = False):
    body = await render_template("signin.html", failed=failed)
    return Response(body, status=401, headers={"WWW-Authenticate": scheme}, content_type="text/html")
