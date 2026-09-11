ARG PYTHON_BASE_IMAGE=python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7
FROM ${PYTHON_BASE_IMAGE}

LABEL bench.repository="scrapy/scrapy"
LABEL bench.base-sha="11079cb1c85b9e75a39a7269943c69d1a975d485"
LABEL bench.purpose="Scrapy SDD test baseline"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPYCACHEPREFIX=/tmp/pycache \
    XDG_CACHE_HOME=/tmp/cache \
    PIP_CACHE_DIR=/tmp/pip-cache \
    TOX_WORK_DIR=/tmp/tox

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/scrapy-source

COPY pyproject.toml README.rst LICENSE AUTHORS ./
COPY scrapy ./scrapy

RUN python -m pip install --no-cache-dir \
        "." \
        "attrs" \
        "coverage>=7.10.6" \
        "httpx2" \
        "pexpect>=4.8.0" \
        "pyftpdlib>=2.0.1" \
        "pygments" \
        "pytest>=8.4.1" \
        "pytest-cov>=7.0.0" \
        "pytest-rerunfailures" \
        "pytest-timeout" \
        "pytest-xdist" \
        "sybil>=1.3.0" \
        "pytest-twisted>=1.14.3" \
    && python -m pip check

ARG BENCH_UID=1000
ARG BENCH_GID=1000

RUN groupadd --gid "${BENCH_GID}" bench \
    && useradd \
        --uid "${BENCH_UID}" \
        --gid "${BENCH_GID}" \
        --create-home \
        --shell /bin/bash \
        bench

USER bench
WORKDIR /workspace

CMD ["sleep", "infinity"]
