# Self-hosting Mellowday

This release serves one User from one local installation. The production command
starts the Conversation Surface, integrated Settings, Reminder and Proactive Chat
schedulers, and the health endpoint in one process.

## Prerequisites

- Python 3.12 or newer
- `pip`
- A writable local directory for Mellowday data
- Chromium installed by Playwright only when running the browser test suite

## Install from a clean checkout

Create and activate a virtual environment, then install the project:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

On POSIX shells, activate with `source .venv/bin/activate`. A release wheel can be
installed in place of `.` with `python -m pip install mellowday-0.1.0-py3-none-any.whl`.

The installed package and its runtime dependencies are independent of the
read-only reference project. Do not copy the reference directory into an
installation or release artifact.

## Local configuration

Production configuration is read from the process environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MELLOWDAY_DATA_DIR` | OS User data directory | Owns the database, audit log, and Skill enablement state |
| `MELLOWDAY_TIMEZONE` | `TZ`, then `UTC` | IANA timezone used for local scheduling and Daily Review |
| `MELLOWDAY_HOST` | `127.0.0.1` | HTTP bind address |
| `MELLOWDAY_PORT` | `8000` | HTTP port |
| `MELLOWDAY_ALLOW_REMOTE` | unset | Must be `1` before a non-loopback bind is accepted |

On Windows the default data directory is `%LOCALAPPDATA%\Mellowday`. On other
platforms it is `$XDG_DATA_HOME/mellowday` or `~/.local/share/mellowday`.
Relative `MELLOWDAY_DATA_DIR` values are resolved when the process starts.

For example, in PowerShell:

```powershell
$env:MELLOWDAY_DATA_DIR = 'D:\MellowdayData'
$env:MELLOWDAY_TIMEZONE = 'Asia/Shanghai'
```

Provider credentials are entered through integrated Settings and stored only in
the local database. They are masked in Settings and omitted from health,
diagnostic, event, and log responses. Local `.env*`, `data/`, and `backups/`
paths at the repository root are ignored by Git, but Mellowday does not require
an environment file or put credentials in one.

The default loopback binding is the safe mode for this single-User application.
There is no multi-user authentication boundary. A non-loopback bind therefore
requires the explicit opt-in variable shown above and should only be placed
behind access control managed by the User.

## Migrate

Apply all idempotent schema initialization and migrations before the first start
and after each upgrade:

```powershell
mellowday migrate
```

Startup also applies the same migrations, so an interrupted deployment can be
started safely after rerunning this command.

## Start and verify

Start the production process:

```powershell
mellowday serve
```

`python -m mellowday serve` is equivalent. Open <http://127.0.0.1:8000/> for the
Conversation Surface and its integrated Settings. Verify the backend at
<http://127.0.0.1:8000/healthz>; a healthy response is `{"ok":true}`.

Both schedulers run for the lifetime of this process. Reminder delivery is
active immediately. Proactive Chat is disabled by default and must be enabled in
Settings. The application starts without a configured Provider and makes no live
model request until the User selects one; chat then reports that no Provider is
configured while Settings and local management remain available.

## Test and build

From a clean checkout, install development requirements and the test browser:

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m mypy src
python -m pytest -q tests/agent_core/test_public_facade.py tests/web_app
python -m pytest -q
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
```

The release workflow performs these checks in a clean GitHub checkout, where the
ignored reference directory is absent. The distribution boundary test builds a
wheel in another isolated project directory, inspects packaged source and static
assets for excluded adapters/configuration, and checks declared dependencies.

## Back up and restore

Create a backup in a new directory outside `MELLOWDAY_DATA_DIR`:

```powershell
mellowday backup D:\MellowdayBackups\before-upgrade-2026-09-01
```

The command uses SQLite's backup operation for a consistent live database
snapshot and copies the local audit and Skill enablement files. The destination
must not already exist. A backup contains Provider credentials as part of the
database, so give it the same access controls as the live data directory.

To restore, stop Mellowday, keep the current data directory as a rollback copy,
copy the backup contents into the configured data directory, run
`mellowday migrate`, and start the service.

## Upgrade

1. Create a backup with `mellowday backup`.
2. Stop the running Mellowday process.
3. Install the new wheel with `python -m pip install --upgrade <wheel>`.
4. Run `mellowday migrate` using the same environment configuration.
5. Run `mellowday serve` and verify `/healthz`, Conversation Surface, Settings,
   and the scheduler settings.

All application-owned data stays under `MELLOWDAY_DATA_DIR`, so changing the
virtual environment or application wheel does not move or replace User data.
