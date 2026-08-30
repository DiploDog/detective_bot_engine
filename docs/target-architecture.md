# Целевая архитектура Detective Bot

Статус: проект этапа 2, без реализации.  
Основной источник требований: `docs/current-state-audit.md`.  
Связанный проект формата игр: `docs/game-format.md`.

## 1. Цели

1. Один Telegram-бот и одна VK-группа/бот предоставляют каталог нескольких игр.
2. Одна и та же `GameDefinition` исполняется одинаково на Telegram и VK; платформы различаются только приемом событий и отображением семантических действий.
3. `killing_margo` и `lora_dein` описываются пакетами данных без game-specific ветвей Python в движке или адаптерах.
4. Сессия явно закрепляет `game_id` и неизменяемую `game_version`.
5. Прогресс и отложенные действия переживают перезапуск процесса/pod благодаря PostgreSQL.
6. Граница приложения полностью асинхронна.
7. Игровой движок тестируется без сети, Telegram/VK и базы данных.
8. Новая похожая детективная игра добавляется в основном новым валидируемым game package и его тестами.

## 2. Не-цели

На текущем этапе и в MVP не проектируются:

- микросервисы, брокер сообщений, CQRS или event sourcing;
- универсальный workflow/BPM-движок;
- CMS и визуальный редактор игр;
- произвольный Python, expression eval или плагины кода в game package;
- fuzzy-, LLM- или semantic matching;
- multiplayer, инвентарь, экономика, достижения, локализация и NPC;
- CDN или общий сервис перекодирования медиа;
- webhook/Ingress как обязательный транспорт MVP;
- окончательная SQL-схема, ORM-модели и миграции;
- автоматическая миграция legacy-кода.

## 3. Архитектурные принципы

### 3.1 Прагматичные Ports & Adapters

Зависимости направлены внутрь:

```text
Telegram / VK / PostgreSQL / filesystem
                    ↓
              application
                    ↓
             pure game engine
```

Движок не импортирует framework-, database- или platform-типы. Application layer знает порты, но не конкретные клиенты. Адаптеры переводят платформенные события в нейтральные команды и семантические ответы обратно в API платформ.

### 3.2 Один модульный монолит, два процесса

Код, движок, game packages и persistence implementation общие. Telegram и VK запускаются как два процесса одного образа с разной конфигурацией. Это не два сервиса с разными бизнес-моделями.

### 3.3 Игры как неизменяемые версионированные данные

Опубликованный пакет `<game_id>/<version>` не редактируется. Исправление контента выпускается новой версией. Активная сессия всегда загружает закрепленную версию.

### 3.4 Явная семантика

Стратегии matching, переходы, эффекты, semantic choices и media asset IDs записываются явно. Случайная разрешительность legacy-парсеров не становится скрытым поведением.

### 3.5 Минимум абстракций

Абстракция допускается, если нужна хотя бы одной текущей игре либо обязательному lifecycle приложения. Поэтому нет отдельной доменной папки поверх engine, generic `Repository[T]`, универсального scheduler product или иерархии Fact/Inventory.

## 4. Предлагаемое дерево репозитория

```text
SobolevBots/
├── src/
│   └── detective_bot/
│       ├── engine/
│       │   ├── model.py
│       │   ├── input.py
│       │   ├── matching.py
│       │   ├── runner.py
│       │   └── validation.py
│       ├── application/
│       │   ├── models.py
│       │   ├── ports.py
│       │   ├── interactions.py
│       │   ├── game_selection.py
│       │   ├── sessions.py
│       │   └── scheduled_delivery.py
│       ├── adapters/
│       │   ├── telegram/
│       │   │   ├── inbound.py
│       │   │   ├── renderer.py
│       │   │   └── runtime.py
│       │   └── vk/
│       │       ├── inbound.py
│       │       ├── renderer.py
│       │       └── runtime.py
│       ├── infrastructure/
│       │   ├── postgres/
│       │   │   ├── sessions.py
│       │   │   ├── scheduled_actions.py
│       │   │   ├── media_cache.py
│       │   │   └── interaction_log.py
│       │   ├── game_catalog.py
│       │   ├── local_media.py
│       │   └── settings.py
│       └── entrypoints/
│           ├── telegram.py
│           └── vk.py
├── games/
│   ├── killing_margo/
│   │   └── 1.0.0/
│   │       ├── manifest.yaml
│   │       ├── game.yaml
│   │       ├── assets/
│   │       └── tests/
│   └── lora_dein/
│       └── 1.0.0/
│           ├── manifest.yaml
│           ├── game.yaml
│           ├── assets/
│           └── tests/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── adapters/
├── tools/
│   └── validate_games.py
├── migrations/
├── deploy/
├── docs/
├── killing_margo/       # legacy, сохраняется до отдельного этапа миграции
└── lora_dein/           # legacy, сохраняется до отдельного этапа миграции
```

Версия включена в путь пакета, потому что runtime обязан одновременно загружать старую версию для активных сессий и новую для новых. Каталоги `migrations/` и `deploy/` отражают будущие места, но на текущем этапе не создаются и не изменяются.

## 5. Ответственность модулей

### `engine/`

Чистая библиотека:

- типы `GameDefinition`, `Scene`, `InputSpec`, `OutcomeRule`, `OutputAction`, `Effect`;
- разбор и matching по явно заданным стратегиям;
- выбор первого подходящего outcome;
- применение переходов и эффектов к снимку сессии;
- выдача `EngineResult`;
- статическая валидация game package.

Engine не знает `/start`, каталог игр, PostgreSQL, update/callback, загрузку файлов или отправку сообщений.

### `application/`

Оркестрация:

- главное меню и доступность игр;
- выбранная/активная сессия;
- создание, продолжение, restart и выход в меню;
- загрузка закрепленной версии игры;
- транзакционная фиксация сессии и исходящих/отложенных действий;
- защита от повторных platform events;
- запуск чистого engine;
- polling и доставка due actions через порт платформы.

### `adapters/telegram/`

Преобразует aiogram Update/Message/CallbackQuery в `IncomingInteraction`; подтверждает callback; отображает semantic choices в Telegram controls; отправляет текст и медиа.

### `adapters/vk/`

Асинхронно получает Group Long Poll events, преобразует сообщения и payload/callback в `IncomingInteraction`, строит VK keyboard/payload и отправляет текст/медиа.

### `infrastructure/`

- реализации PostgreSQL ports;
- загрузка и кеширование валидированных immutable game packages;
- разрешение локальных media paths относительно корня package;
- кеш удаленных Telegram `file_id` и VK attachment IDs;
- настройки из environment.

### `games/`

Только контент, правила, semantic asset declarations и engine-level characterization tests. Никаких импортов Python и platform IDs.

### `tests/` и `tools/`

Общие unit/integration/adapter tests и тонкий CLI валидатора. Package-specific сценарии находятся рядом с версией игры.

## 6. Компоненты времени выполнения

1. **Telegram runtime** — aiogram polling, application use cases, Telegram renderer/sender, встроенный lightweight due-action pump для строк `platform=telegram`.
2. **VK runtime** — async VK Group Long Poll, те же application/engine, VK renderer/sender, due-action pump для `platform=vk`.
3. **PostgreSQL** — сессии, выбор активной сессии, журнал взаимодействий, durable outbound/scheduled actions и media cache.
4. **Game catalog** — read-only packages внутри Docker image, загружаемые и валидируемые при старте.
5. **Локальные assets** — файлы внутри конкретной версии package; удаленные platform IDs считаются кешем, а не источником истины.

Отдельный HTTP API, broker и scheduler service не нужны.

## 7. Границы Application, Engine и Adapter

| Ответственность | Слой |
|---|---|
| `/start`, главное меню, список игр | Application + rendering adapter |
| Выбрать/продолжить/restart/покинуть игру | Application |
| Проверить доступность/latest version | Application через `GameCatalogPort` |
| Разобрать ответ по game DSL | Engine |
| Выбрать outcome, изменить scene/variables | Engine |
| Telegram `Message` / VK event | Adapter |
| Callback/payload encoding и acknowledgement | Adapter |
| Inline/reply keyboard representation | Adapter |
| Локальный файл, Telegram file_id, VK attachment ID | Infrastructure + adapter |
| Транзакция и блокировка сессии | PostgreSQL infrastructure |
| Доставка due semantic action | Application pump + platform sender |

### Минимальный набор use cases

1. `HandleIncomingInteraction`
   - распознает application command/menu interaction;
   - иначе находит выбранную сессию и вызывает engine;
   - сохраняет результат и action batches.
2. `SelectGame`
   - продолжает существующую незавершенную сессию либо создает новую на версии, выбранной application/catalog policy;
   - назначает ее выбранной для данного platform user/chat.
3. `RestartGame`
   - требует явного подтверждения;
   - завершает/помечает старую сессию как superseded;
   - отменяет ее pending actions;
   - создает новую сессию на версии, выбранной application/catalog policy.

`OpenMainMenu`, `ContinueGame` и `LeaveGame` — небольшие ветви первых двух use cases, а не отдельные классы, пока их логика не усложнится.

### Чистый контракт engine

Концептуально:

```python
EngineResult = engine.handle(
    game_definition,
    session_snapshot,
    semantic_input,
    now,
)
```

Результат содержит новый snapshot, немедленные `OutputAction`, запросы schedule/cancel, outcome ID и данные для структурированного interaction log. Engine ничего не сохраняет и не отправляет.

## 8. Жизненный цикл сессии

### Концептуальная `GameSession`

```text
id
platform
external_user_id
external_chat_id
game_id
game_version
current_scene
status: in_progress | completed | superseded
variables: typed JSON-compatible values
revision
started_at
updated_at
completed_at?
```

`revision` нужен для optimistic concurrency и отклонения устаревших кнопок. Он увеличивается один раз, когда принятый interaction действительно меняет scene/status/variables, создает schedule request либо выполняется start/application mutation. Обработанный `stay` только с `OutputAction`, простая выдача fallback, повторная отправка уже созданного action и delivery retry revision не меняют. Поэтому одна revision-bound панель статей остается применимой после нескольких непродвигающих чтений.

Отдельное application-level соответствие `PlayerContext -> selected_session_id?` определяет текущую игру в конкретном Telegram/VK-чате. Оно не является частью game scene.

### Одновременный прогресс

Пользователь может иметь незавершенный прогресс в обеих играх. В одном platform/chat context выбрана только одна сессия, которой направляется обычный игровой ввод. Выход в меню очищает выбор, но не уничтожает прогресс. Выбор другой игры переключает указатель; предыдущая остается `in_progress`.

Один человек в Telegram и VK считается разными player contexts, пока не появится отдельное требование account linking.

### Основные переходы lifecycle

```text
нет выбранной сессии
  -> главное меню
  -> select game
      -> continue existing in_progress session
      OR create new selected catalog version
  -> play
  -> leave to menu (progress retained)
  -> complete
  -> menu / explicit new run
```

`/start` всегда открывает меню. Он не меняет `GameSession`.

## 9. Жизненный цикл выбора игры

1. Adapter превращает `/start` или платформенный аналог в `open_menu`.
2. Application получает из `GameCatalogPort` версии, разрешенные внешней catalog policy; availability не хранится внутри immutable package.
3. Для каждой игры отмечается наличие resumable session.
4. Application возвращает semantic choices: `select_game(killing_margo)`, `select_game(lora_dein)`.
5. Adapter отображает их подходящими платформенными кнопками.
6. При выборе `SelectGame`:
   - продолжает закрепленную старую сессию, если она есть;
   - иначе создает сессию на выбранной catalog version и исполняет `on_enter` entry scene.
7. Обычный текст маршрутизируется только в `selected_session_id`.

На этапе 3 простой filesystem catalog считает все найденные валидные packages установленными. Он выбирает highest SemVer только по явному `get_latest`; продуктовая availability появится позже на application/catalog boundary.

## 10. Жизненный цикл версии игры

1. `manifest.yaml` содержит SemVer-подобную immutable `version`.
2. Version manifest не содержит mutable `enabled`: публикация и доступность определяются внешней application/catalog policy.
3. Новая сессия получает выбранную catalog version; простой filesystem catalog умеет явно вернуть highest installed SemVer, но не решает продуктовую availability.
4. Существующая сессия всегда загружает точные `game_id + game_version`.
5. Старые packages нельзя удалять, пока на них ссылаются resumable/pending sessions.
6. Изменение опубликованного каталога версии запрещается policy/CI; исправление выпускается как новая версия.
7. Явный restart создает новую сессию на версии, выбранной catalog policy. UI должен предупредить, если версия отличается.
8. Миграция активной сессии между версиями не входит в MVP; при необходимости это будет отдельный явно протестированный инструмент.

## 11. Порты persistence для PostgreSQL

SQL-схема здесь намеренно не определяется.

### `GameCatalogPort`

Это filesystem/image port, а не обязательно таблица PostgreSQL:

- `list_games() -> list[GameSummary]`
- `list_versions(game_id) -> list[str]`
- `get(game_id, version) -> GameDefinition`
- `get_latest(game_id) -> GameDefinition`
- `has(game_id, version) -> bool`

Definitions кешируются в памяти как immutable объекты после успешной валидации.

### `SessionRepository`

- `get(session_id, for_update=False)`
- `get_selected(player_context, for_update=False)`
- `find_resumable(player_context, game_id)`
- `list_resumable(player_context)`
- `create(session)`
- `save(session, expected_revision)`
- `set_selected(player_context, session_id | None)`
- `mark_superseded(session_id, completed_at)`

Нет generic CRUD: операции отражают lifecycle приложения.

### `ScheduledActionRepository`

Один порт обслуживает немедленные durable output batches (`due_at=now`) и будущие:

- `enqueue(action_batch)`
- `enqueue_unique(action_batch, idempotency_key)`
- `claim_due(platform, now, limit, lease_until)`
- `mark_delivered(action_id, delivered_at)`
- `reschedule_after_failure(action_id, next_attempt_at, error_code)`
- `cancel_for_session(session_id)`
- `release_expired_claims(now)`

Claim должен быть атомарным; PostgreSQL implementation может использовать row locking/`SKIP LOCKED`, но это деталь реализации, не DSL.

### `MediaCacheRepository`

- `get(platform, bot_identity, game_id, game_version, asset_id, source_digest)`
- `put(...)`
- `invalidate(...)`

Кеш необязателен для корректности: при miss adapter загружает локальный asset и сохраняет remote reference.

### `InteractionLogPort`

- `append(record)`
- опциональные административные запросы позднее, не нужные engine.

Runtime не восстанавливает состояние из этого журнала; это не event sourcing.

### Транзакционная граница

Application выполняет под одной PostgreSQL-транзакцией:

1. блокировку/проверку revision сессии;
2. deduplication входного platform event;
3. сохранение нового snapshot;
4. append структурированной interaction record;
5. enqueue immediate и delayed action batches;
6. изменение selected session при необходимости.

Инфраструктура предоставляет простой transaction scope/Unit of Work только для этой границы. Репозитории не получают самостоятельных несогласованных commit.

## 12. Durable scheduled action

### Выбранный дизайн

Используется одна PostgreSQL-backed очередь semantic action batches. Это transactional outbox с `due_at`, но не broker и не отдельная платформа планирования.

При достижении Margo article scene engine выдает:

```text
schedule_id: reveal_articles
due_at: now + 300 seconds
session_id / platform / chat destination
idempotency_key
semantic output batch: reminder + article choices
guard: session still in_progress and current_scene == articles
```

Application сохраняет session и scheduled row атомарно. Поэтому crash до commit не меняет ничего, а crash после commit не теряет действие.

### Delivery pump

Каждый platform runtime запускает одну async background coroutine:

1. запрашивает небольшой batch due rows своей платформы;
2. атомарно ставит lease;
3. повторно загружает сессию и проверяет declarative guard;
4. передает semantic actions renderer/sender той же платформы;
5. помечает delivered либо планирует retry с ограниченным backoff.

Уникальный `idempotency_key`, например `<session_id>:<scene_revision>:reveal_articles`, предотвращает повторную постановку. Claim lease позволяет подобрать действие после падения worker. Удаленная API-доставка не может быть строго exactly-once, поэтому возможный редкий дубль принимается и минимизируется platform idempotency/delivery record.

Originating revision входит в idempotency key и аудит, но не является неявным delivery guard: чтение статьи меняет revision, однако не должно отменять reveal, пока сессия остается `in_progress` в `margo_articles`. Проверяется только guard, явно материализованный из DSL.

### Почему без отдельного Deployment

Telegram runtime доставляет только Telegram rows и уже владеет Telegram token; VK runtime — только VK rows и VK token. При одной реплике каждого это проще третьего worker с обоими секретами. При будущем масштабировании `claim_due` обеспечивает конкуренцию реплик.

Отдельный worker Deployment понадобится только при существенно большей нагрузке или переходе на webhook/scaled-to-zero процессы; для MVP он избыточен.

### Немедленные ответы

Тот же механизм может сохранять batch с `due_at=now`. После commit текущий процесс сразу пытается claim/send его, а background pump страхует сбой. Это предотвращает ситуацию «прогресс сохранен, ответ навсегда потерян» без второго инфраструктурного механизма.

## 13. Медиа

### Семантическая модель

Game content ссылается только на:

```text
safe_closed
safe_open
phone_recording
final_police_report
```

`manifest.yaml` сопоставляет asset ID с типом и относительным локальным путем. Путь разрешается от корня конкретной версии package, нормализуется и не может выходить за него.

### Доставка Telegram

1. Проверить media cache по asset ID и digest.
2. При наличии использовать Telegram `file_id`.
3. При miss отправить локальный файл соответствующим API-методом.
4. Полученный `file_id` сохранить как оптимизационный кеш.

### Доставка VK

1. Проверить кеш VK attachment reference.
2. При miss загрузить локальный файл через async VK API/upload flow.
3. Сохранить attachment ID с учетом bot identity и digest.

Platform IDs не попадают обратно в game package. Изменение файла меняет digest и естественно инвалидирует кеш. CDN для текущих четырех Margo assets не нужен.

## 14. Ответственность Telegram adapter

- запуск/остановка aiogram polling;
- перевод Message/CallbackQuery в `IncomingInteraction`;
- structural normalization: platform/user/chat/event IDs, text либо semantic choice;
- немедленный `callback.answer()` как техническое подтверждение;
- кодирование/декодирование компактного callback payload с session/revision/interaction/value;
- отклонение/понятный ответ для устаревшей кнопки;
- рендеринг `text`, `media`, `choices`;
- выбор Telegram media API по semantic media type;
- async retry/classification Telegram API errors;
- отсутствие game-specific handlers.

Текстовая game normalization (`lower`, exact, aliases) остается в engine согласно DSL.

## 15. Ответственность VK adapter

- Group Long Poll consumer для одной группы;
- перевод message events и message-event payload в `IncomingInteraction`;
- вызов callback acknowledgement, если используется callback button;
- рендеринг semantic choices в VK keyboard/payload либо текстовый fallback;
- async отправка сообщений и upload media;
- mapping VK `user_id`/`peer_id`;
- reconnect/backoff long poll без завершения процесса на единичном timeout;
- отсутствие game-specific if/elif.

Legacy `vk_api.VkLongPoll` и user-token topology не являются ограничением target.

## 16. Целевая async-модель

Все внешние границы имеют async contracts:

```text
await interaction_handler.handle(...)
await session_repository.get/save(...)
await platform_sender.send(...)
async for event in platform_event_source:
    ...
```

Telegram продолжает использовать aiogram 3.

Для VK рекомендуемый кандидат — **VKBottle 4.x**:

- заявлен как asyncio VK API framework;
- поддерживает bot/group long polling;
- предоставляет async `run_polling`, API calls, keyboards и raw `MESSAGE_EVENT`;
- позволяет использовать group token вместо legacy user Long Poll.

На момент проектирования публичные источники показывают `vkbottle 4.10.0` и Python `>=3.10,<4.0`, однако перед реализацией обязательны внешняя проверка актуального релиза и короткий POC:

1. Group Long Poll с целевой группой и ее настройками событий.
2. Async send text/media upload.
3. Callback keyboard + `MESSAGE_EVENT` acknowledgement.
4. Reconnect/backoff и clean shutdown.
5. Совместимость с целевой версией Python и observability hooks.

Если библиотека окажется недостаточно поддерживаемой, fallback — небольшой VK adapter на `aiohttp` поверх официальных `groups.getLongPollServer` и VK API. Прямой клиент не должен проникнуть в application/engine. Запуск sync `vk_api` через thread pool возможен лишь как временный migration bridge, не target.

Проверенные на этапе проектирования внешние источники:

- [VKBottle repository](https://github.com/vkbottle/vkbottle);
- [VKBottle 4.10.0 на PyPI](https://pypi.org/project/vkbottle/);
- [async `run_polling` и Bot API](https://vkbottle.readthedocs.io/ru/dev/high-level/bot/);
- [пример VK `MESSAGE_EVENT`](https://github.com/vkbottle/vkbottle/blob/master/examples/high-level/callback_buttons.py).

Эти ссылки подтверждают направление, но не заменяют POC с реальной VK-группой, ее permissions и фактическими media types.

## 17. Обработка ошибок

### Категории

1. **Неверный пользовательский ввод** — обычный `OutcomeRule`, не exception.
2. **Устаревший choice/callback** — application validation; сообщение «кнопка устарела», без изменения сессии.
3. **Конфликт revision/дубликат event** — повторно прочитать или вернуть уже сохраненный результат; не исполнять engine дважды.
4. **Ошибка game package** — ERROR валидатора; deployment/preflight не проходит.
5. **Transient platform/DB error** — ограниченный retry/backoff; action остается pending.
6. **Permanent media/config error** — action помечается failed/dead после лимита, структурированный alert; состояние не маскируется.
7. **Неожиданная ошибка engine** — correlation ID, rollback транзакции, нейтральный ответ без внутренних деталей.

Application не ловит `Exception` без классификации и не проглатывает ошибки. Platform runtime не завершается от единичного timeout long poll.

## 18. Наблюдаемость и история сессии

### Структурированные логи

Минимальные поля:

- correlation ID и external event ID;
- platform, game ID/version, session ID;
- scene before/after, outcome ID;
- delivery/scheduled action ID, attempt, latency;
- тип ошибки без token, payload и полного пользовательского текста.

### Метрики

- interactions по platform/game/outcome;
- invalid/wrong ответы по scene;
- completion count/duration;
- due-action lag, retry/failure count;
- platform API latency/error count;
- package validation status.

### Решение по session history

В MVP сохраняется простой append-only `session_interactions`-подобный журнал:

- session, scene before/after, input kind;
- matched outcome/rule, invalid reason;
- timestamps и external event ID;
- без возможности восстанавливать session и без raw user text по умолчанию.

Это дешево — одна запись в уже существующей транзакции — и дает диагностику, воронку и места застревания. Сохранение полного текста, особенно непризнанных ответов, включается только отдельной privacy policy с retention/доступом; по умолчанию запрещено.

## 19. Топология K3s

```text
Deployment telegram-bot (replicas: 1)
    PLATFORM=telegram
    Telegram Secret
    polling + Telegram due-action pump
                \
                 PostgreSQL
                /
Deployment vk-bot (replicas: 1)
    PLATFORM=vk
    VK group Secret
    Group Long Poll + VK due-action pump

Один Docker image:
    общий application + engine + infrastructure
    обе версии adapters
    все необходимые immutable game packages/assets
```

Разные entrypoints/config выбирают platform runtime. Long polling остается MVP transport, поэтому Ingress/webhook не требуется. HPA, RabbitMQ, NATS и Redis не добавляются. PostgreSQL может быть существующим управляемым/кластерным компонентом; его конкретное развертывание вне scope этого этапа.

## 20. Требования безопасности

1. VK и Telegram tokens находятся только в environment/Kubernetes Secret.
2. Оба обнаруженных legacy VK token следует считать раскрытыми и сменить до target запуска.
3. Secrets, callback payload internals и полный пользовательский текст не журналируются.
4. Логи и interaction history имеют явные retention/access policies.
5. Media paths разрешаются только внутри package root; использование process CWD запрещено.
6. Game package проходит schema и path validation до загрузки.
7. Callback содержит session/revision либо серверный opaque token; чужой/устаревший callback не меняет сессию.
8. Admin/ops actions отделены от игровых semantic choices и авторизуются.
9. PostgreSQL credentials выдаются с минимально необходимыми правами.

## 21. Последствия для будущей миграции

- Legacy entrypoints остаются reference implementations до characterization tests.
- Сначала фиксируются game packages/tests, затем pure engine, затем adapters.
- Известный VK hint offset не переносится; логический hint связан со своей scene.
- Margo delay фиксируется как 300 секунд и становится durable action.
- Lora scene 2 сохраняет subset rule min 2/max 3.
- Различия Telegram/VK остаются только в controls/media rendering.
- Redis FSM не является target source of truth; перенос активного прогресса потребует отдельного mapping legacy step -> scene.
- Старые media IDs не являются game content; отсутствующие локальные assets нужно получить до migration cutover.
- Переход можно проводить по одной игре/платформе, не удаляя legacy.

## 22. Риски и нерешенные вопросы

### Риски

1. Старые game versions должны оставаться в образе, пока есть resumable sessions; нужна pre-deploy проверка ссылок.
2. Platform API не гарантирует exactly-once send; durable delivery минимизирует, но не исключает редкий дубль.
3. Callback payload limits Telegram/VK могут потребовать compact/opaque encoding.
4. Отсутствующие Margo assets блокируют проверку media parity.
5. Async VK library может измениться до реализации; POC обязателен.
6. Слишком подробный YAML может стать неудобным без хорошего validator и package tests.

### Нерешенные продуктовые вопросы

1. Канонические display titles двух игр.
2. Точные тексты меню, continue/restart confirmations и post-completion UX.
3. Следует ли Margo delayed article list отменять после раннего перехода к killer scene. Предложенный guard отменяет его вне `articles`.
4. Требуется ли поддержка групповых чатов; модель сохраняет `external_chat_id`, но MVP разумно ограничить личными сообщениями.
5. Privacy/retention policy для опционального хранения непризнанных пользовательских ответов.
6. Как долго завершенные/superseded sessions и старые packages должны храниться.

## Target runtime flow

### Обычное входящее взаимодействие

```text
Telegram/VK event
    -> adapter structural normalization
    -> HandleIncomingInteraction
    -> deduplicate external event
    -> session lookup / selected-session lookup
    -> load pinned game_id + game_version
    -> pure engine
    -> transaction:
         persist session
         append structured interaction
         enqueue semantic response batches
    -> commit
    -> claim immediate batch
    -> platform renderer
    -> Telegram/VK API
    -> mark delivered
```

### Отложенное взаимодействие

```text
engine ScheduleAction(now + 300s)
    -> same transaction: session + unique scheduled row
    -> PostgreSQL waits durably
    -> platform runtime due-action pump
    -> claim with lease
    -> verify declarative session guard
    -> platform renderer
    -> Telegram/VK API
    -> delivered
       OR retry/backoff
       OR cancel if guard no longer holds
```

## Итог self-review

1. Одна `GameDefinition` не содержит platform API и исполняется обеими платформами.
2. Lora scene 2 выражается declarative subset/min/max rule.
3. Margo article mode выражается несколькими scene interactions без game-specific Python.
4. Hint — generic semantic choice в отдельной короткой scene, без callback data в package.
5. 300-секундное действие хранится в PostgreSQL и переживает pod restart.
6. Старая активная сессия закреплена на immutable version; версию новой выбирает внешняя catalog policy.
7. Engine — чистая функция и тестируется in-memory.
8. В target нет Fact/Inventory, broker, microservices или других неподтвержденных механизмов.
