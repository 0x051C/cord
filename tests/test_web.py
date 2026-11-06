import asyncio
import base64
import re

import pytest

from application import pipeline, reports
from application.pipeline_config import Department
from models.registry import PAPER_KINDS
from web import create_app
from web.auth import AuthenticationFailed, KerberosAuthenticator, Negotiated, NoAuthenticator
from web.data import paginate


def call(app, path, headers=None, client=None):
    """Synchronous wrapper around the Quart test client: returns (response, body text)."""

    async def go():
        test_client = client or app.test_client()
        response = await test_client.get(path, headers=headers or {})
        return response, await response.get_data(as_text=True)

    return asyncio.run(go())


@pytest.fixture
def ran(generator, pipeline_config, fs, repository):
    for kind in PAPER_KINDS:
        generator.write_csv(pipeline_config.input_dir, kind, 20, invalid_ratio=0.1)
    report = pipeline.run(config=pipeline_config, fs=fs, repository=repository)
    pipeline.run(config=pipeline_config, fs=fs, repository=repository)  # second run: nothing new
    return report


@pytest.fixture
def app(ran, repository, pipeline_config):
    return create_app(repository=repository, authenticator=NoAuthenticator(), config=pipeline_config)


# ------------------------------------------------------------------ journal
def test_runs_are_journaled(ran, repository):
    runs = repository.list_runs()
    assert [run["status"] for run in runs] == ["no_new_records", "ok"]
    first = runs[1]
    assert first["id"] == ran.id
    assert first["valid_rows"] == 18 * len(PAPER_KINDS)
    assert first["invalid_rows"] == 2 * len(PAPER_KINDS)
    assert {file["kind"] for file in first["files"]} == {kind.key for kind in PAPER_KINDS}
    assert set(first["routed"]) == {department.value for department in Department}
    errors = repository.run_errors([ran.id])
    assert len(errors) == first["error_count"] >= first["invalid_rows"]
    assert {"file", "row", "field", "message", "value", "context"} <= set(errors[0])


def test_failed_run_is_journaled(generator, pipeline_config, fs, repository, monkeypatch):
    generator.write_csv(pipeline_config.input_dir, PAPER_KINDS[0], 5)

    def broken_export(*args, **kwargs):
        raise OSError("output share is read-only")

    monkeypatch.setattr(reports, "export", broken_export)
    with pytest.raises(OSError):
        pipeline.run(config=pipeline_config, fs=fs, repository=repository)
    run = repository.list_runs()[0]
    assert run["status"] == "failed" and "read-only" in run["message"]


# -------------------------------------------------------------------- pages
@pytest.mark.parametrize("path", ["/", "/runs", "/errors", "/departments", "/departments?department=impdiv&kind=waybill",
                                  "/partials/dashboard", "/partials/departments/expdiv/declaration", "/healthz"])
def test_pages(app, path):
    response, body = call(app, path)
    assert response.status_code == 200, body


def test_dashboard_shows_last_import(app, ran):
    _, body = call(app, "/")
    assert "No new records" in body  # status of the latest run
    assert f"/runs/{ran.id}" in body  # the import the cards are about
    assert re.search(r"Valid rows \(last import\)</span>\s*<span class=\"value ok\">72<", body)


def test_run_page(app, ran):
    response, body = call(app, f"/runs/{ran.id}")
    assert response.status_code == 200
    for file in ran.files:
        assert file["name"] in body
    assert call(app, "/runs/does-not-exist")[0].status_code == 404


def test_unknown_department_or_kind(app):
    assert call(app, "/departments?department=nope")[0].status_code == 404
    assert call(app, "/api/departments/impdiv/nope")[0].status_code == 404


def test_security_headers(app):
    response, _ = call(app, "/")
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"


# ---------------------------------------------------------------------- api
def test_api_errors(app, ran, repository):
    total = len(repository.run_errors([ran.id]))
    response, _ = call(app, f"/api/errors?run={ran.id}&size=5")
    page = asyncio.run(response.get_json())
    assert page["last_row"] == total and len(page["data"]) == 5

    query = f"/api/errors?run={ran.id}&filter[0][field]=kind&filter[0][type]=like&filter[0][value]=waybill&sort[0][field]=row&sort[0][dir]=desc"
    filtered = asyncio.run(call(app, query)[0].get_json())
    rows = [error["row"] for error in filtered["data"]]
    assert filtered["last_row"] == 2 and rows == sorted(rows, reverse=True)
    assert {error["kind"] for error in filtered["data"]} == {"Waybills"}

    error_id = page["data"][0]["id"]
    response, body = call(app, f"/partials/errors/{error_id}")
    assert response.status_code == 200 and page["data"][0]["file"] in body
    assert call(app, "/partials/errors/123456789")[0].status_code == 404


def test_api_department_records_follow_routing(app, pipeline_config):
    pattern = re.compile(pipeline_config.routing_patterns[Department.IMPORT])
    page = asyncio.run(call(app, "/api/departments/impdiv/declaration?size=1000")[0].get_json())
    assert page["data"], "the mock data should route some declarations to the import department"
    assert all(pattern.search(row["op_type"]) for row in page["data"])


def test_api_runs(app):
    runs = asyncio.run(call(app, "/api/runs")[0].get_json())
    assert [run["status_label"] for run in runs] == ["No new records", "OK"]


def test_paginate_bounds():
    import pandas as pd

    frame = pd.DataFrame({"a": range(10)})
    assert paginate(frame, {"page": "3", "size": "4"})["data"] == [{"a": 8}, {"a": 9}]
    assert paginate(frame, {"page": "x"})["last_page"] == 1


# --------------------------------------------------------------- kerberos
class FakeKerberos(KerberosAuthenticator):
    """Stands in for the KDC-backed ticket validation; everything around it is the real code."""

    def accept(self, token: bytes) -> Negotiated:
        if token == b"ticket-alice":
            return Negotiated("alice@EXAMPLE.LOCAL", out_token=b"mutual")
        if token == b"ticket-mallory":
            return Negotiated("mallory@OTHER.REALM")
        raise AuthenticationFailed("bad ticket")


@pytest.fixture
def kerberos_app(ran, repository, pipeline_config):
    auth = FakeKerberos(hostname="cord.example.local", allowed_realms={"EXAMPLE.LOCAL"})
    return create_app(repository=repository, authenticator=auth, config=pipeline_config)


def negotiate(token: bytes) -> dict:
    return {"Authorization": "Negotiate " + base64.b64encode(token).decode()}


def test_kerberos_challenge(kerberos_app):
    response, body = call(kerberos_app, "/")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Negotiate"
    assert "Windows sign-in required" in body
    assert call(kerberos_app, "/healthz")[0].status_code == 200
    assert call(kerberos_app, "/static/app.js")[0].status_code == 200


@pytest.mark.parametrize("headers", [{"Authorization": "Negotiate !!!"}, {"Authorization": "Basic YTpi"}, negotiate(b"forged")])
def test_kerberos_rejects_bad_tokens(kerberos_app, headers):
    response, _ = call(kerberos_app, "/", headers=headers)
    assert response.status_code == 401


def test_kerberos_sign_in_and_session(kerberos_app):
    client = kerberos_app.test_client()
    response, body = call(kerberos_app, "/", headers=negotiate(b"ticket-alice"), client=client)
    assert response.status_code == 200
    assert "alice@EXAMPLE.LOCAL" in body
    assert response.headers["WWW-Authenticate"] == "Negotiate " + base64.b64encode(b"mutual").decode()
    assert "cord_session=" in response.headers["Set-Cookie"] and "HttpOnly" in response.headers["Set-Cookie"]
    # the session cookie authenticates the following (htmx) requests
    assert call(kerberos_app, "/partials/dashboard", client=client)[0].status_code == 200


def test_kerberos_principal_not_allowed(kerberos_app):
    response, body = call(kerberos_app, "/", headers=negotiate(b"ticket-mallory"))
    assert response.status_code == 403 and "mallory@OTHER.REALM" in body


def test_allow_lists():
    auth = KerberosAuthenticator(hostname="h", allowed_principals={"bob@corp"}, allowed_realms={"EXAMPLE.LOCAL"})
    assert auth.is_allowed("Bob@CORP") and auth.is_allowed("x@example.local") and not auth.is_allowed("x@CORP")
    assert KerberosAuthenticator(hostname="h").is_allowed("anyone@ANY")


def test_unauthenticated_server_only_on_loopback():
    from web.server import serve

    class Settings(dict):
        pass

    with pytest.raises(SystemExit, match="loopback"):
        serve(Settings(web_auth="none"), host="0.0.0.0", port=8000)
