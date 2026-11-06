"""
Authentication.

* ``kerberos`` (production): HTTP Negotiate / SPNEGO. A domain-joined browser uses
  the user's ticket granting ticket to obtain a service ticket for
  ``HTTP/<web_kerberos_hostname>`` and sends it in ``Authorization: Negotiate``;
  the server validates it with its keytab (Linux, ``web_kerberos_keytab``) or
  its service account (Windows, SSPI). No password reaches the application.
  Only Kerberos is accepted (multi-leg NTLM fallbacks are rejected). After a
  successful handshake the principal is kept in a signed session cookie.
* ``none`` (local profile only): everybody is ``local``; only allowed when the
  server listens on a loopback address.
"""

import base64
import binascii
import ipaddress
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from application.logging_setup import validation_logger

SESSION_PRINCIPAL = "principal"


class AuthenticationFailed(Exception):
    pass


@dataclass
class Negotiated:
    principal: str
    out_token: Optional[bytes] = None  # mutual authentication token for the response


class Authenticator(Protocol):
    challenge: Optional[str]  # WWW-Authenticate scheme, None when no authentication is needed

    def accept(self, token: bytes) -> Negotiated: ...

    def is_allowed(self, principal: str) -> bool: ...


class NoAuthenticator:
    challenge = None

    def accept(self, token: bytes) -> Negotiated:
        return Negotiated(principal="local")

    def is_allowed(self, principal: str) -> bool:
        return True


@dataclass
class KerberosAuthenticator:
    hostname: str
    service: str = "HTTP"
    allowed_principals: set[str] = field(default_factory=set)  # lower case "user@REALM"
    allowed_realms: set[str] = field(default_factory=set)  # upper case "REALM"
    challenge: str = "Negotiate"

    def accept(self, token: bytes) -> Negotiated:
        import spnego

        try:
            context = spnego.server(hostname=self.hostname, service=self.service, protocol="negotiate")
            out_token = context.step(token)
        except Exception as e:  # spnego raises a range of SpnegoError / OSError subclasses
            raise AuthenticationFailed(f"Negotiate token rejected: {e}") from e
        if not context.complete:
            raise AuthenticationFailed("Negotiate did not complete in one step (NTLM is not accepted, use Kerberos)")
        if context.negotiated_protocol != "kerberos":
            raise AuthenticationFailed(f"Unexpected protocol {context.negotiated_protocol!r}, Kerberos is required")
        principal = context.client_principal
        if not principal:
            raise AuthenticationFailed("No client principal in the Kerberos ticket")
        return Negotiated(principal=principal, out_token=out_token)

    def is_allowed(self, principal: str) -> bool:
        if not self.allowed_principals and not self.allowed_realms:
            return True
        realm = principal.rpartition("@")[2].upper()
        return principal.lower() in self.allowed_principals or realm in self.allowed_realms


def parse_negotiate_header(value: Optional[str]) -> Optional[bytes]:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "negotiate" or not token.strip():
        return None
    try:
        return base64.b64decode(token.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _as_set(value, normalise) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    return {normalise(str(v).strip()) for v in value if str(v).strip()}


def build_authenticator(settings) -> Authenticator:
    mode = str(settings.get("web_auth", "kerberos")).lower()
    if mode == "none":
        return NoAuthenticator()
    if mode != "kerberos":
        raise ValueError(f"Unknown web_auth setting: {mode!r} (expected 'kerberos' or 'none')")
    hostname = settings.get("web_kerberos_hostname")
    if not hostname:
        raise ValueError("web_kerberos_hostname is required with web_auth = 'kerberos' (the FQDN users browse to)")
    keytab = settings.get("web_kerberos_keytab")
    if keytab:
        os.environ["KRB5_KTNAME"] = str(keytab)  # read by GSSAPI on Linux; Windows uses the service account
    authenticator = KerberosAuthenticator(
        hostname=str(hostname),
        service=str(settings.get("web_kerberos_service", "HTTP")),
        allowed_principals=_as_set(settings.get("web_allowed_principals"), str.lower),
        allowed_realms=_as_set(settings.get("web_allowed_realms"), str.upper),
    )
    if not authenticator.allowed_principals and not authenticator.allowed_realms:
        validation_logger.warning(
            "web: any authenticated Kerberos principal may use the dashboard "
            "(set web_allowed_principals / web_allowed_realms to restrict it)"
        )
    return authenticator
