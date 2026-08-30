# UM Telegram bot

## Локальный запуск

1. Создайте файл окружения:

   ```bash
   cp .env.example .env
   ```

2. Укажите актуальный токен Telegram-бота в `.env`.
3. Запустите сервисы:

   ```bash
   docker compose up --build -d
   ```

4. Посмотрите логи:

   ```bash
   docker compose logs -f bot
   ```

Остановить проект можно командой `docker compose down`. Данные Redis сохраняются
в named volume `redis-data`; для удаления состояния используйте
`docker compose down -v`.

## Развёртывание в k3s

Манифесты используют `BOT_TOKEN` и `TELEGRAM_PROXY` из существующего файла
`.env` и создают Kubernetes Secret через Kustomize. Формат прокси:

```dotenv
TELEGRAM_PROXY=socks5://user:password@proxy-host:proxy-port
```

Соберите образ и импортируйте его в containerd k3s:

```bash
docker build -t um-bot:latest .
docker save um-bot:latest | sudo k3s ctr images import -
```

Примените манифесты:

```bash
sudo k3s kubectl apply -k .
sudo k3s kubectl -n tgbot-ns rollout status deployment/bot
```

Проверка состояния и логов:

```bash
sudo k3s kubectl -n tgbot-ns get pods
sudo k3s kubectl -n tgbot-ns logs deployment/bot -f
```
