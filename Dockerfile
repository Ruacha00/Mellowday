# syntax=docker/dockerfile:1
#
# MellowDay container image.
#
# Three stages: a shared `base`, a `dependencies` layer that only changes when
# the dependency set changes, and `production`.
#
# Building this image never calls a model and never needs a credential. `pip
# install .` resolves the declared Python dependencies and the packaged browser
# assets; every model setting (key, base URL, model id) is supplied at run time
# through the environment. There is deliberately no build-time ARG carrying a
# secret.

FROM python:3.12-slim-bookworm AS base
WORKDIR /app

# Explicit UTF-8. This project has been bitten by cp936 (GBK) defaults mangling
# Chinese copy in files and on stdout, so the container pins the encoding rather
# than inheriting the base image's POSIX locale. C.UTF-8 is built into Debian and
# needs no locale generation step.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS dependencies
# Runtime dependencies, mirroring [project] dependencies in pyproject.toml.
# Installing them here (before any source is copied) keeps a source-only edit
# from invalidating this slow layer. Drift is self-healing: the production stage
# runs a plain `pip install .`, which installs anything declared there and not
# yet present.
RUN pip install --no-cache-dir \
        "openai>=1.0.0" \
        "anthropic>=0.25.0" \
        "fastapi>=0.110.0" \
        "uvicorn>=0.27.0" \
        "python-dotenv>=1.0.0"

FROM base AS production

# Reuse the dependency layer instead of re-resolving it.
COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Non-root runtime identity. uid 1000 is what the named data volume must be
# writable by, so the account is created before /app/data is prepared.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mellowday

# Only these two paths enter the image: the metadata pip needs and the package
# itself. .env / .env.* are excluded from the build context as well, so a
# credential has two independent reasons not to end up in a layer.
COPY --chown=mellowday:mellowday pyproject.toml ./
COPY --chown=mellowday:mellowday src ./src

# Non-editable install of the real package. This is also the packaging check:
# setuptools only copies mellowday/web_app/static/* into the wheel because
# [tool.setuptools.package-data] declares it, so a missing browser client fails
# the build's own smoke check below rather than showing up as a 404 later.
RUN pip install --no-cache-dir . \
 && rm -rf /app/src /app/build /app/pyproject.toml \
 && test -f /usr/local/lib/python3.12/site-packages/mellowday/web_app/static/index.html \
 && python -c "import mellowday.paths as p; assert (p.static_dir() / 'index.html').is_file(), p.static_dir()"

# Persistent state lives here. The directory is created and owned by the runtime
# user so a *fresh* named volume inherits that ownership when Docker populates it
# from the image.
RUN mkdir -p /app/data && chown -R mellowday:mellowday /app /app/data

USER mellowday

EXPOSE 8000

# Probes the real HTTP surface, not just the process. `python` is used because
# the slim image ships no curl or wget.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).read()"

CMD ["python", "-m", "mellowday.web_app", "--host", "0.0.0.0", "--port", "8000"]
