# waybill-declaration_parsing_models

Parsing practice for a Django/FastAPI ETL: customs declarations (GTD), their
corrections, clearance statements and waybills (TTN) arrive as `^`-delimited
files, are validated with Pydantic models, stored, and routed to department
reports (xlsx).

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Local test environment (SQLite + mock data)

The `local` profile (`config/profiles/local.toml`) keeps everything inside
`sandbox/`: input folder, SQLite database, reports and logs. No SMB share or
MongoDB is needed.

```sh
python main.py --env local seed            # mock input files -> sandbox/input/
python main.py --env local run             # validate -> sandbox/cord.sqlite3 -> sandbox/output/*/
python main.py --env local reset           # delete sandbox/
```

`seed` options:

| option | default | |
|---|---|---|
| `--rows N` | 50 | rows per document type |
| `--kinds K` | all | repeatable or comma separated: `declaration`, `declarationupdates`, `clearancestatement`, `waybill` (e.g. `--kinds waybill,declaration`) |
| `--invalid-ratio R` | 0.1 | share of deliberately broken rows (to see validation errors in `sandbox/logs/validation.log`) |
| `--target csv\|db\|both` | csv | `csv` writes input files for `run`; `db` inserts records straight into SQLite, spread over the last `days_to_fetch` days |
| `--seed N` | random | reproducible data |

Mock data is generated from the model schema: the generator walks each model's
fields in column order and fills them using the active validation settings
(allowed authorities, country/currency codes, declaration types, date formats).
Every generated row is validated with the real model, so a schema change the
generator does not know about fails loudly (`application/mock_data.py`).

`seed` and `reset` refuse to run with the production profile. `python main.py --help`
(or `<command> --help`) lists every option.

`CORD_ENV=local` can be used instead of `--env local`, and any setting can be
overridden with `CORD_<SETTING>` environment variables.

## Production

```sh
python main.py run      # same as: python main.py
```

Uses `config/validation_config.py` + `config/cord.toml` + `config/.secrets.ini`
(the latter two are local, git-ignored files): SMB share via `smbprotocol`
(kerberos), MongoDB via `pymongo`. Settings that select the backends:

```toml
filesystem = "smb"            # or "local" (also works with UNC paths on Windows)
storage_backend = "mongo"     # or "sqlite" (+ sqlite_path)
log_dir = "."                 # where validation.log / smb.log are written
fallback_dump_path = "."      # output_<time>.json when the database is unreachable
waybill_output_filename = "ttn_{0} — {1}"
```

Validation rules are read from `config/validation.ini` when present, with the
defaults in `config/validation_config.py` otherwise (`tools/add_setting.py`
adds new ones).

## Web dashboard

A read-only dashboard (Quart + htmx + [Tabulator](https://tabulator.info) grids)
showing every run, the files it processed, each validation error with its
source row, and which department receives which records.

```sh
python main.py --env local serve          # http://localhost:8000/  (no sign-in, loopback only)
python main.py serve                      # production profile: Kerberos sign-in
```

| Page | Shows |
|---|---|
| Dashboard | last run / last import, valid and invalid rows, records per department and document type, recent runs (refreshes every 30 s) |
| Runs | all runs; a run's page lists its files, the records its reports sent to each department, and its errors |
| Errors | validation errors of a run: filter by file / type / field / message, click a row for the whole source row |
| Departments | the stored records of the last `days_to_fetch` days per department and document type, routed like the xlsx reports |

Every pipeline run is recorded in the same storage as the records (SQLite
locally, MongoDB in production, collections `_runs` and `_errors`), so the
dashboard must use the same `storage_backend` settings as the pipeline. A run
whose database was unreachable cannot be recorded (its records go to the
`output_*.json` fallback dump as before).

htmx and Tabulator are vendored in `web/static/vendor/` (versions and npm
integrity hashes in `VERSIONS.txt`), the dashboard needs no internet access.

### Kerberos sign-in (production)

Users are signed in with their Windows login: the browser uses the user's
ticket granting ticket to get a service ticket for `HTTP/<host>` and sends it
with `Authorization: Negotiate`; the server validates it, no password is
involved. Only Kerberos is accepted (no NTLM fallback). The principal is then
kept in a signed, HttpOnly session cookie.

1. **Service principal** — the dashboard is reached by a DNS name, e.g.
   `cord.example.local` (use an A record; browsers build the SPN from the
   canonical name). Register `HTTP/cord.example.local` on a service account:
   `setspn -S HTTP/cord.example.local EXAMPLE\svc-cord`
2. **Server credentials**
   - Windows: run the dashboard as `svc-cord` (SSPI is used, no keytab).
   - Linux: export a keytab and install GSSAPI support:
     ```sh
     ktpass -princ HTTP/cord.example.local@EXAMPLE.LOCAL -mapuser EXAMPLE\svc-cord -crypto AES256-SHA1 -ptype KRB5_NT_PRINCIPAL -pass * -out http.keytab   # on a domain controller
     sudo apt install libkrb5-dev   # or krb5-devel
     pip install "pyspnego[kerberos]"
     ```
3. **Settings** (`cord.toml`; the secret preferably as the `CORD_WEB_SECRET_KEY` environment variable):
   ```toml
   web_auth = "kerberos"
   web_host = "0.0.0.0"
   web_port = 8443
   web_kerberos_hostname = "cord.example.local"
   web_kerberos_keytab = "/etc/cord/http.keytab"   # Linux only
   web_allowed_realms = ["EXAMPLE.LOCAL"]             # and/or web_allowed_principals = ["user@EXAMPLE.LOCAL"]
   web_tls_certfile = "/etc/cord/tls.crt"          # recommended: the session cookie becomes Secure
   web_tls_keyfile = "/etc/cord/tls.key"
   web_session_hours = 8
   ```
   Without `web_secret_key` a random key is generated at start, so sessions
   do not survive restarts. Without an allow list any principal of the domain
   may sign in (a warning is logged).
4. **Browsers** must trust the site for integrated authentication: Edge/Chrome
   on Windows — the site in the *Local intranet* zone or the
   `AuthServerAllowlist` policy; Firefox — `network.negotiate-auth.trusted-uris`.

`web_auth = "none"` is refused unless the server listens on a loopback address.

## What a run does

1. Input files matching `re_updates` / `re_statement` / `re_declaration` /
   `re_waybill` are validated row by row; errors (with the row content) go to
   `validation.log`. Processed files are renamed `*.old`, then `*.old.old` on
   the next run, then moved to `old/`.
2. Valid records are stored, one collection/table per document type.
3. If the run stored anything, records of the last `days_to_fetch` days are
   routed by `re_for_both` / `re_for_impdiv` / `re_for_expdiv` and written as
   xlsx to the common / import / export folders.
4. Logs are copied next to the reports; a `__CLEAR__` file in the input folder
   truncates them afterwards.

## Layout

```
main.py                         CLI (run / seed / reset / serve)
application/
  configuration_handling.py     dynaconf settings and profiles
  pipeline.py                   the run, step by step
  pipeline_config.py            paths/patterns resolved from settings
  ingest.py                     file discovery, rotation, csv reading, row validation
  reports.py                    department routing, xlsx export
  filesystem.py                 local / SMB file access
  storage/                      Repository interface, SQLite and MongoDB implementations
  mock_data.py                  schema driven mock data
  logging_setup.py
web/
  __init__.py                   Quart app, Kerberos sign-in hook, security headers
  auth.py                       Negotiate / Kerberos authentication
  views.py data.py              pages, htmx partials, grid JSON endpoints
  templates/ static/            htmx pages, vendored htmx + Tabulator
models/
  registry.py                   document types: file pattern, table, routing column, report name
  declaration.py statement.py waybill.py  ...
  logic/pydantic_helper.py      flat row <-> nested model mapping
config/
  validation_config.py          validation settings (+ optional validation.ini)
  profiles/local.toml           local test profile
tests/
```

## Tests

```sh
.venv/bin/python -m pytest
```

The tests use the local profile and temporary folders/databases.
