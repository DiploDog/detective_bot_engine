# VK adapter Detective Bot

## Назначение

Один VK community bot принимает Group Long Poll events, превращает их в
`IncomingInteraction`, вызывает существующий `ApplicationService` и отрисовывает
semantic outputs. Игровые правила, matching и YAML остаются вне adapter.

```text
VK event
    -> inbound mapping
    -> ApplicationService
    -> outbound_deliveries
    -> claim/send delivery service
    -> renderer / sender
```

Transport: **VKBottle 4.11**. Live VK API не используется в automated tests.

## Inbound mapping

`platform = vk`, `external_user_id = str(from_id|user_id)`,
`external_chat_id = str(peer_id)`. Личные сообщения: `peer_id == from_id`.
Dedup keys: `vk:message:{id}` и `vk:event:{event_id}`.

| VK event | Application interaction |
|---|---|
| `начать` / `start` / `/start` | `OpenMenu` |
| `меню` / `menu` / `/menu` | `LeaveToMenu` |
| `заново` / `restart` / `/restart` | `RequestRestart` выбранной session |
| message text | `SubmitGameInput(TextInput)` |
| callback payload | select/restart/leave/menu или `ChoiceInput` |

Нетекстовые сообщения игнорируются. Adapter не проверяет правильность ответа.

## Callback / buttons

Inline keyboard с `type=callback`. Compact payload в JSON `{"p": "..."}`,
тот же compact contract, что у Telegram (`m`, `l`, `s|...`, `g|...`).
`MESSAGE_EVENT` сначала получает `send_empty_answer()`, затем application handle.

Невалидный или stale payload даёт notice без вызова engine:

    Эта кнопка уже устарела. Используйте актуальное сообщение.

## Media

Asset path берётся из validated `FileSystemGameCatalog.asset_paths`.
Persistent cache key:

    community_id + asset SHA-256 + VK media kind (photo/audio/document)

Значение cache — reusable VK attachment (`photo-...` / `doc-...`).
Stale attachment повторяет upload и обновляет cache. Token не хранится.

| Semantic type / policy | VK method |
|---|---|
| image | photo upload + `messages.send` |
| audio | document upload (`DocMessagesUploader`); community token не использует Audio API |
| document или settings document-asset set | document upload |
| `final_police_report` по умолчанию | photo, как legacy VK |

## Delivery

Общие claim/lease/retry/dead/materialize mechanics в `adapters/delivery.py`.
VK worker claim'ит только `platform=vk`. Immediate outputs не send'ятся напрямую
из processor: после `handle()` идёт `deliver_source_event`. Background pump —
fallback в том же process.

## Runtime

`python -m detective_bot.entrypoints.vk` читает env:

- `VK_GROUP_TOKEN`
- `VK_GROUP_ID`
- `DATABASE_URL`
- `GAMES_ROOT`
- `LOG_LEVEL`
- `VK_DOCUMENT_ASSETS`

Polling: `BotPolling.listen()` с reconnect/backoff внутри VKBottle.
`listen()` отдаёт Long Poll envelope `{ts, updates}`; runtime передаёт в
dispatcher только элементы `updates` с полем `type`, как `Bot.run_polling()`.
Служебные `failed`/`ts` в dispatcher не попадают.
Shutdown: `polling.stop()`, pump stop, `http_client.close()`, engine dispose.
Legacy `killing_margo/vk/main.py` и `lora_dein/main.py` не используются.
