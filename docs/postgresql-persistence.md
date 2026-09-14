# PostgreSQL persistence Detective Bot

## Схема

PostgreSQL является source of truth для application lifecycle. Game definitions
и assets остаются immutable filesystem packages и в БД не копируются.

- `player_contexts` — platform route identity и nullable
  `selected_session_id`. Тройка `platform`, `external_user_id`,
  `external_chat_id` уникальна.
- `game_sessions` — opaque string session ID, владелец, pinned game/version,
  application lifecycle status, engine status/scene/revision, JSONB variables и
  lifecycle timestamps.
- `processed_events` — только player context, внешний event ID и время.
  Raw platform payload отсутствует.
- `scheduled_actions` — durable schedule request, origin revision,
  due/claim/lease/retry/delivery/cancellation state.
- `session_interactions` — append-only диагностический журнал без raw input.
- `telegram_media_cache` — Telegram `file_id` по `bot_id + SHA-256 + media kind`.
- `outbound_deliveries` — transactional outbox immediate semantic outputs.
  Platform-neutral JSONB `action_payload` с type discriminator, `sequence_no`
  внутри batch, `due_at` для immediate (`now`) и поля claim/lease/retry под
  следующий delivery pump. Telegram/VK объекты не сериализуются.

Partial unique index `uq_game_session_resumable` разрешает не более одной
`in_progress` session для пары player context + game. Session ID хранится как
`VARCHAR(128)`: application и engine продолжают считать его opaque string и не
зависят от PostgreSQL UUID types.

## Transaction boundary и Unit of Work

`ApplicationService` получает одну `UnitOfWorkFactory`. Каждый public use case
создаёт одну async UoW, а `handle` выполняет в ней весь interaction:

```text
IncomingInteraction
        ↓
UoW transaction
        ├── processed_event
        ├── session
        ├── selection
        ├── interaction_log
        ├── scheduled_action
        └── immediate outbound_deliveries
        ↓
      COMMIT
```

`PostgresUnitOfWork` предоставляет `sessions`, `scheduled_actions`,
`processed_events`, `interaction_log`, `outbound_deliveries`, `commit()` и
`rollback()`. Выход по exception или без commit откатывает transaction.
Repositories не выполняют самостоятельных commit. Повтор `external_event_id`
не создаёт второй outbound batch. Restart отменяет только `pending` outbound
старой session; `delivered` не трогает.

## Concurrency и locks

Session mutation использует optimistic conditional update:

```text
UPDATE game_sessions
SET revision = new_revision, ...
WHERE id = session_id AND revision = expected_revision
```

Нулевой row count означает `SessionConflict`; автоматического retry нет.
Player-context row блокируется `FOR UPDATE` при чтении/изменении selection,
чтобы input routing, game switch и restart не меняли указатель одновременно.
Session rows не блокируются без необходимости: revision защищает snapshot.

Concurrent creation дополнительно защищена partial unique index. Чужую session
нельзя выбрать: repository проверяет её `player_context_id` до обновления FK.

## Event deduplication

`try_register(player_context, external_event_id, processed_at)` выполняет
`INSERT ... ON CONFLICT DO NOTHING` по unique player/event key. `True` получает
только первая transaction. Registration находится в той же transaction, что
engine result, log и schedules; rollback удаляет её и позволяет безопасный retry.

## Scheduled action lifecycle

Статусы: `pending`, `claimed`, `delivered`, `cancelled`, `dead`.
Уникальность `(session_id, origin_revision, idempotency_key)` делает повторный
handoff одной engine mutation идемпотентным, но не объединяет разные revisions.

`claim_due` выбирает due rows своей platform через join с session/player context:

```text
SELECT ... FOR UPDATE OF scheduled_actions SKIP LOCKED
```

Claim задаёт lease и увеличивает attempts. Параллельные workers получают
непересекающиеся rows. `release_expired_claims` возвращает истёкшие leases в
`pending`; failure можно reschedule, успешную доставку — отметить delivered.
Production sender/pump в этот этап не входит.

Restart в одной transaction помечает старую session `superseded`, отменяет её
`pending`/`claimed` schedules и `pending` outbound rows, создаёт новую latest
session, обновляет selection и enqueue start outputs новой session.

## Interaction log

Для каждого вызова engine сохраняются session/event IDs, scene до/после,
interaction/outcome, input kind, status, invalid reason и timestamp. Raw text,
Telegram/VK payload, tokens и другие secrets не сохраняются. Журнал не
используется для восстановления state и не является event sourcing.

## Время, migrations и tests

Business timestamps приходят из injected application clock и сохраняются как
`TIMESTAMPTZ`. Variables записываются новым JSONB object целиком; ORM mutable
tracking не используется.

Alembic head — `20260905_0003` поверх `20260905_0002`. Production не
использует `Base.metadata.create_all()`. URL передаётся engine/session factory
явно; Alembic принимает `DATABASE_URL`.

Integration suite использует только реальный PostgreSQL, разные connections для
concurrency tests и очистку таблиц между tests. Проверяются migration
downgrade/upgrade, JSONB round-trip, revision conflict, partial unique race,
atomic event registration/rollback, schedule idempotency, SKIP LOCKED,
lease recovery, реальные Lora/Margo flows, switching и restart rollback.
