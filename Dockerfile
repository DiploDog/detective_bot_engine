FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY src/ ./src/

RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GAMES_ROOT=/app/games

RUN groupadd --gid 10001 detective-bot \
    && useradd --uid 10001 --gid detective-bot --no-create-home \
        --home-dir /app --shell /usr/sbin/nologin detective-bot

WORKDIR /app

COPY --from=builder /wheels/ /wheels/
RUN python -m pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY --chown=detective-bot:detective-bot src/ ./src/
COPY --chown=detective-bot:detective-bot games/ ./games/
COPY --chown=detective-bot:detective-bot migrations/ ./migrations/
COPY --chown=detective-bot:detective-bot alembic.ini ./

USER detective-bot

CMD ["python", "-m", "detective_bot.entrypoints.telegram"]
