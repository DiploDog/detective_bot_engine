# Detective Bot on K3s

Манифесты разворачивают PostgreSQL 16, Telegram/VK long-polling processes,
отдельный Alembic Job и ежедневный logical backup в namespace `private`.
Ingress, webhook, Redis и broker не используются.

## Перед deployment

1. Опубликуйте production image в Docker Hub.
2. В `kustomization.yaml` замените только `images.newName` и `images.newTag`.
   Это единственное место настройки repository/tag приложения; используйте
   immutable release tag.
3. Скопируйте `secret.example.yaml` за пределы repository, замените все
   `REPLACE_*` и примените полученный Secret. Значения `POSTGRES_USER`,
   `POSTGRES_PASSWORD` и `POSTGRES_DB` должны совпадать с credentials внутри
   `DATABASE_URL`; специальные символы в URL должны быть percent-encoded.

```bash
kubectl apply -f deploy/k3s/namespace.yaml
cp deploy/k3s/secret.example.yaml /tmp/detective-bot-secret.yaml
${EDITOR:-vi} /tmp/detective-bot-secret.yaml
kubectl apply -f /tmp/detective-bot-secret.yaml
kubectl kustomize deploy/k3s > /tmp/detective-bot-k3s.yaml
```

Не коммитьте заполненный Secret. Template намеренно не включён в
`kustomization.yaml`.

## Порядок deployment

Ресурсы имеют label `detective-bot.io/deployment-phase`. Сначала применяются
PostgreSQL и storage, затем отдельный migration Job, и только после его
успешного завершения — application Deployments и backup CronJob.

```bash
kubectl apply -f /tmp/detective-bot-k3s.yaml \
  -l detective-bot.io/deployment-phase=foundation
kubectl -n private rollout status statefulset/detective-bot-postgres

kubectl -n private delete job detective-bot-migrate --ignore-not-found
kubectl apply -f /tmp/detective-bot-k3s.yaml \
  -l detective-bot.io/deployment-phase=migration
kubectl -n private wait --for=condition=complete \
  job/detective-bot-migrate --timeout=300s

kubectl apply -f /tmp/detective-bot-k3s.yaml \
  -l detective-bot.io/deployment-phase=application
```

Alembic не является initContainer: неуспешный Job блокирует процедуру до запуска
Telegram/VK. При обновлении сначала опубликуйте новый immutable tag, повторите
render и migration phase, затем примените application phase.

## Storage и backups

Data PVC и backup PVC имеют размер 5Gi, `ReadWriteOnce` и
`storageClassName: local-path-prov`. Backup запускается ежедневно в 03:00 UTC,
использует `pg_dump -Fc`, сначала атомарно завершает новый dump и только затем
удаляет файлы старше 30 дней. `concurrencyPolicy: Forbid` не допускает
параллельные backup jobs.

Backup на `local-path` защищает от логических ошибок и позволяет восстановить
предыдущий dump, но **не защищает от потери самой VM или её диска**. Для такой
аварии backups необходимо дополнительно копировать во внешнее хранилище.
