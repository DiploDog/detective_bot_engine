# Application lifecycle Detective Bot

## Граница слоя

`application` координирует каталог игр, persistence ports и чистый engine. Он знает
маршрут пользователя, выбранную сессию и lifecycle, но не знает Telegram/VK API,
SQL, YAML parsing и правил конкретной игры. Adapter позднее преобразует событие
платформы в `IncomingInteraction` и отрисует semantic application outputs.

## PlayerContext и сессия

`PlayerContext` состоит из `platform`, `external_user_id` и
`external_chat_id`. Контексты Telegram и VK намеренно не связываются.

`ApplicationSession` хранит application metadata рядом с единственным
authoritative `SessionSnapshot` engine. `session_id`, `game_id` и
`game_version` доступны как свойства snapshot и не дублируются отдельными
изменяемыми полями. Application добавляет:

- владельца `PlayerContext`;
- `created_at`, `updated_at`, `completed_at`, `superseded_at`;
- вычисляемый status `in_progress`, `completed` или `superseded`.

Scene, variables и engine revision существуют только в `SessionSnapshot`.

## Выбранная сессия и меню

`SessionRepository` хранит отношение
`PlayerContext -> selected_session_id | None`. У пользователя могут одновременно
существовать незавершённые Lora и Margo, но обычный игровой input получает только
выбранная сессия.

`open_menu` очищает только selected relation и не изменяет snapshots. Меню строится
из catalog manifests и resumable sessions. Поэтому renderer получает
`display_title`, `game_id`, version и состояние `new`/`continue` без hardcode
названий в application.

## Select и resume

`select_game` сначала ищет незавершённую сессию игрока для `game_id`.

- Если она есть, application проверяет наличие точной pinned версии, выбирает
  сессию и возвращает `session_resumed`. Engine не вызывается, а `on_enter` не
  повторяется.
- Если её нет, catalog выбирает latest installed version. Application создаёт
  пустой snapshot revision 0, один раз вызывает `engine.start`, сохраняет
  полученную revision 1 и возвращает entry actions.

Последующий `TextInput`/`ChoiceInput` загружает только `game_id + game_version`
из сессии. Отсутствующая версия приводит к `GameVersionUnavailable`; silent
upgrade запрещён. Опциональный session ID на `SubmitGameInput` защищает от
кнопки другой выбранной сессии, а revision semantic choice дополнительно
проверяется engine.

При `complete` snapshot и application status становятся `completed`;
`completed_at` берётся из injected clock. Сессия может остаться выбранной, но
следующий input не создаёт новую игру.

## Restart

Restart является двухшаговым application flow.

1. `request_restart(session_id)` проверяет владельца и pinned package и возвращает
   `ShowRestartConfirmation`, не меняя progress.
2. `confirm_restart(session_id)` проверяет latest package, помечает старую сессию
   `superseded`, вызывает `cancel_for_session` и
   `outbound_deliveries.cancel_pending_for_session`, создаёт новую сессию на
   latest версии через `engine.start` и выбирает её. Delivered outbound rows
   старой session не отменяются.

`cancel_restart` оставляет snapshot и selected relation без изменений.
Session ID находится в semantic confirmation; отдельное transient restart-state
хранилище не требуется.

## Scheduled actions

`EngineResult.scheduled` передаётся в `ScheduledActionRepository.add` после
успешного сохранения snapshot. Due rows materialize generic: pinned package,
template guard, enqueue semantic actions в `outbound_deliveries`. При restart
вызывается `cancel_for_session` старой сессии. Guard не пускает reveal, если
session superseded или ушла из `margo_articles`.

## Deduplication и concurrency

`external_event_id`, вместе с `PlayerContext`, является ключом deduplication.
Атомарный `try_register` выполняется в начале Unit of Work. Уже
зарегистрированное событие возвращает `DuplicateInteraction`, не вызывая engine.
Registration коммитится или откатывается вместе со всем use case.

Каждый `save` и `mark_superseded` получает `expected_revision`. Repository обязан
сравнить его с persisted engine revision и поднять `SessionConflict` при
расхождении. Application не делает неявный retry и не перезаписывает новое
состояние stale snapshot.

Production PostgreSQL Unit of Work объединяет session save, schedule handoff,
selected relation, interaction log, processed event и immediate outbound
deliveries в одной transaction. In-memory tests используют тот же UoW contract
и rollback semantics. Повтор `external_event_id` не создаёт второй outbound
batch. Telegram send из outbox на этом этапе не выполняется.
