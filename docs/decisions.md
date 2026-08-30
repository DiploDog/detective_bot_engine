# Архитектурные решения этапа 2

Формат: краткие ADR. Решения описывают target design, но не означают начало реализации.

## ADR-001: один идентификатор бота на платформу

**Статус:** зафиксировано продуктом.

**Решение:** один Telegram bot token обслуживает все игры Telegram; одна VK group identity обслуживает все игры VK.

**Следствие:** выбор игры и активной сессии — application concern. Game package не содержит token или platform application ID.

## ADR-002: игры поставляются как data packages

**Статус:** зафиксировано продуктом.

**Решение:** новая похожая игра добавляется immutable package `games/<game_id>/<version>/` с manifest, YAML definition, assets и tests.

**Следствие:** game-specific Python handlers/if-ветви запрещены. Новый engine primitive допускается только при подтвержденной механике, не выражаемой текущим DSL.

## ADR-003: один общий чистый engine

**Статус:** зафиксировано архитектурным принципом.

**Решение:** Telegram и VK вызывают один pure engine, принимающий definition, session snapshot, semantic input и clock.

**Следствие:** engine не импортирует aiogram, VK framework, PostgreSQL client и filesystem/network APIs; его результат — новый snapshot и semantic actions/effects.

## ADR-004: PostgreSQL — source of truth

**Статус:** зафиксировано продуктом.

**Решение:** sessions, active selection, scheduled/outbound actions, media cache и структурированный interaction log хранятся в PostgreSQL.

**Следствие:** Redis не является core requirement. Его можно добавить только после измеренного требования к кешу/координации, а не для хранения основного прогресса.

## ADR-005: модульный монолит без брокера

**Статус:** зафиксировано ограничениями проекта.

**Решение:** один codebase и Docker image запускаются двумя platform processes. Микросервисы, RabbitMQ/NATS, CQRS и event sourcing не используются.

**Следствие:** границы модулей остаются явными, но deployment прост: Telegram, VK и PostgreSQL.

## ADR-006: явные match strategies

**Статус:** зафиксировано продуктом.

**Решение:** schema v1 поддерживает `exact`, `aliases`, осознанный `contains`, `numeric_selection` и semantic `choice`.

**Следствие:** `aliases` использует равенство после объявленной normalization; accidental substring вроде `не` внутри произвольного слова не сохраняется. Regex/fuzzy/LLM matching отложены.

## ADR-007: semantic media IDs

**Статус:** зафиксировано продуктом.

**Решение:** game content ссылается на `safe_closed`, `safe_open`, `phone_recording`, `final_police_report` и другие semantic IDs.

**Следствие:** manifest указывает локальный asset; Telegram `file_id` и VK attachment ID являются инфраструктурным кешем, привязанным к platform/bot/package version/digest.

## ADR-008: версия закрепляется за сессией

**Статус:** зафиксировано продуктом.

**Решение:** опубликованный package immutable и не содержит `enabled`; session хранит `game_id + game_version`. Версию новой session выбирает внешняя application/catalog policy, старая продолжает свою.

**Следствие:** старые packages сохраняются, пока существуют resumable/pending sessions. Неявной миграции прогресса между versions нет.

## ADR-009: durable delayed и immediate delivery через PostgreSQL

**Статус:** предложено.

**Решение:** semantic action batches сохраняются транзакционно с session и имеют `due_at`; platform runtime забирает их lightweight async pump с lease/retry/idempotency.

**Следствие:** Margo article reveal через 300 секунд переживает pod restart. Отдельный scheduler Deployment и broker для MVP не нужны.

## ADR-010: restart — явный application use case

**Статус:** зафиксировано продуктом.

**Решение:** `/start` открывает меню и не сбрасывает прогресс. Restart требует отдельного выбора/подтверждения, supersede старой session, отмены ее pending actions и создания новой.

**Следствие:** reset/restart не является effect в game YAML.

## ADR-011: hints моделируются generic semantic choice

**Статус:** предложено.

**Решение:** hint prompt — короткая scene с `choices` output и `choice` input yes/no; результат возвращает в логический вопрос.

**Следствие:** в package нет `hint_yes`, callback data, `InlineKeyboardMarkup` или `VkKeyboard`. Известный VK offset bug не переносится.

## ADR-012: простой журнал взаимодействий, не event sourcing

**Статус:** предложено.

**Решение:** в той же транзакции добавляется append-only structured interaction record: scene/outcome/input kind/timestamps, без raw text по умолчанию.

**Следствие:** журнал используется для диагностики и аналитики, но не является источником восстановления session. Полный пользовательский текст требует отдельной privacy/retention policy.

## ADR-013: async VK через проверяемый adapter

**Статус:** предложено, требуется POC.

**Решение:** основной кандидат — VKBottle 4.x с Group Long Poll и async API. Fallback — небольшой adapter на `aiohttp` и официальном VK Group Long Poll.

**Следствие:** legacy sync `vk_api` не определяет target. До выбора dependency необходимо проверить актуальную версию, callback events, uploads, reconnect и целевую Python version.

## ADR-014: legacy intent сохраняется, очевидные дефекты — нет

**Статус:** зафиксировано продуктом.

**Решение:** сохраняются утвержденные игровые правила, тексты и порядок, но не accidental parser behavior, VK hint offset и тестовая задержка 5 секунд.

**Следствие:** Margo имеет одинаковую game semantics на обеих платформах; delay равен 300 секундам. Lora scene 2 сохраняет фактическое subset rule min 2/max 3.
