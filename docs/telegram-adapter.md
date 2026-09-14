# Telegram adapter Detective Bot

## Назначение

Один Telegram-бот принимает Update, превращает его в `IncomingInteraction`,
вызывает существующий `ApplicationService` и отрисовывает semantic outputs.
Игровые правила, matching и YAML остаются вне adapter.

```text
Telegram Update
    -> inbound mapping
    -> ApplicationService
    -> outbound_deliveries
    -> claim/send delivery service
    -> renderer / sender
```

## Inbound mapping

`platform = telegram`, `external_user_id = str(from_user.id)`,
`external_chat_id = str(chat.id)`. Dedup key: `telegram:{update_id}`.

| Telegram event | Application interaction |
|---|---|
| `/start` | `OpenMenu` |
| `/menu` | `LeaveToMenu` |
| `/restart` | `RequestRestart` выбранной session |
| message text | `SubmitGameInput(TextInput)` |
| compact callback | select/restart/leave/menu или `ChoiceInput` |

Нетекстовые сообщения игнорируются. Adapter не проверяет правильность ответа.

## Callback format

Один compact contract, лимит 64 байта:

- `m` — open_menu
- `l` — leave_to_menu
- `s|{game_id}` — select_game
- `r|{sid}` / `y|{sid}` / `n|{sid}` — request/confirm/cancel restart
- `g|{sid}|{rev}|{interaction}|{i|s}{value}` — game choice

32-hex session ID сжимается в callback (`h` + base64url). Короткий opaque ID
передаётся как `p...`. Game semantics в callback не хранятся: только
application action либо identity interaction/value/revision.

## Menu, selection, choices

`ShowGameMenu` становится inline keyboard. Display title и `new`/`continue`
берутся из application output. `/start` только открывает меню и не restart.

`ChoicesAction` — тот же generic keyboard path для hint, articles, restart
confirmation и menu. Labels без options читаются из InputSpec текущей scene.

## Stale protection

Game callback несёт `session_id` и `revision`. Application/engine mismatch
рисует нейтральное:

    Эта кнопка уже устарела. Используйте актуальное сообщение.

Невалидный callback_data обрабатывается так же, без вызова engine.

## Media

Asset path берётся из validated `FileSystemGameCatalog.asset_paths`.
Local `FSInputFile` при cache miss. Persistent cache key:

    bot_id + asset SHA-256 + Telegram media kind (photo/audio/document)

Stale `file_id` повторяет upload и обновляет cache. Token не хранится.

| Semantic type / policy | Telegram method |
|---|---|
| image | `send_photo` |
| audio | `send_audio` |
| document или settings document-asset set | `send_document` |

Финальный полицейский JPG остаётся image в package; Telegram policy этапа 7A
отправляет его как document, как legacy TG. Это rendering policy, не game change.

Порядок `OutputAction` сохраняется.

## Private chats и ошибки

Group/supergroup получают notice и не создают session.

`callback.answer()` вызывается сразу. Handler exception не роняет polling:
пользователь видит generic message, лог содержит platform, event id, action type
и категорию ошибки. Token, DATABASE_URL, raw text и полный callback не
логируются.

## Runtime

`python -m detective_bot.entrypoints.telegram` читает env:

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `GAMES_ROOT`
- `LOG_LEVEL`
- `TELEGRAM_DOCUMENT_ASSETS`

Composition root собирает catalog, PostgreSQL UoW, ApplicationService, Bot и
Dispatcher. Import не открывает сеть/БД. Startup валидирует catalog; shutdown
закрывает bot session и dispose engine. Transport — long polling, одна replica.

## Delivery

Immediate и scheduled outputs идут через один outbox. После commit runtime
claim/send тот же batch; background pump — fallback. Semantics: at-least-once.
`ApplicationResult` больше не отправляется отдельным direct-send путём.

Scheduled template materialize generic: pinned package, declarative guard,
enqueue template.actions. Delivery pump живёт в том же process, что polling.
