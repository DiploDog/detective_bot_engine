# Containerization

Один production image содержит общий engine/application, оба platform adapter,
production game packages с assets и Alembic migrations. Сборка использует
Python 3.12 multi-stage image: builder создаёт wheel с runtime dependencies,
финальный stage устанавливает wheel без dev extras и работает от пользователя
`detective-bot` (UID/GID 10001).

```bash
docker build -t detective-bot:local .
```

Внутри image рабочий каталог — `/app`, а `GAMES_ROOT` по умолчанию равен
`/app/games`.

```bash
docker run --rm \
  -e TELEGRAM_BOT_TOKEN \
  -e DATABASE_URL \
  detective-bot:local \
  python -m detective_bot.entrypoints.telegram

docker run --rm \
  -e VK_GROUP_TOKEN \
  -e VK_GROUP_ID \
  -e DATABASE_URL \
  detective-bot:local \
  python -m detective_bot.entrypoints.vk

docker run --rm \
  -e DATABASE_URL \
  detective-bot:local \
  alembic upgrade head
```

Дополнительные runtime settings: `LOG_LEVEL`,
`TELEGRAM_DOCUMENT_ASSETS` и `VK_DOCUMENT_ASSETS`. Tokens и PostgreSQL URL
не встраиваются в image и должны передаваться средой запуска или Secret.
