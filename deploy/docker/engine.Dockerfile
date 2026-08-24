# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419

FROM debian:bookworm-slim AS sqlite-builder
ARG SQLITE_VERSION=3530400
ARG SQLITE_SHA256=0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl build-essential \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl --fail --show-error --location --retry 3 \
      "https://www.sqlite.org/2026/sqlite-autoconf-${SQLITE_VERSION}.tar.gz" -o sqlite.tar.gz \
 && echo "${SQLITE_SHA256}  sqlite.tar.gz" | sha256sum -c - \
 && tar -xzf sqlite.tar.gz --strip-components=1 \
 && ./configure --prefix=/opt/sqlite --enable-shared --disable-static \
      CFLAGS="-O2 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_JSON1" \
 && make -j2 \
 && make install

FROM ${PYTHON_IMAGE} AS runtime
ARG MOVA_GIT_SHA=unknown
LABEL org.opencontainers.image.title="MOVA FPL engine" \
      org.opencontainers.image.revision="${MOVA_GIT_SHA}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    LD_LIBRARY_PATH=/usr/local/lib \
    MOVA_GIT_SHA=${MOVA_GIT_SHA}
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates chromium coinor-cbc curl fonts-liberation tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 mova \
 && useradd --uid 10001 --gid 10001 --home-dir /var/lib/mova-fpl --no-create-home mova
COPY --from=sqlite-builder /opt/sqlite/lib/libsqlite3.so* /usr/local/lib/
COPY --from=sqlite-builder /opt/sqlite/bin/sqlite3 /usr/local/bin/sqlite3
RUN ldconfig
WORKDIR /app
COPY requirements/runtime.lock /tmp/runtime.lock
RUN python -m pip install --no-cache-dir --requirement /tmp/runtime.lock \
 && python -m pip check
COPY mova_fpl /app/mova_fpl
COPY deploy/docker/engine-entrypoint.sh /usr/local/bin/mova-entrypoint
RUN chmod 0755 /usr/local/bin/mova-entrypoint \
 && python -c "import sqlite3; assert tuple(map(int, sqlite3.sqlite_version.split('.'))) >= (3,51,3), sqlite3.sqlite_version"
ENV HOME=/var/lib/mova-fpl
RUN install -d -m 0750 -o 10001 -g 10001 /var/lib/mova-fpl
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini","--","/usr/local/bin/mova-entrypoint"]
CMD ["python","-m","mova_fpl.ops.cli","serve"]
