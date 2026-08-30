# Миграция Lora Dein 1.0.0

## 1. Source implementation

Источник игровой семантики и текстов: `lora_dein/main.py`, прежде всего `scenes`, `parse_answer`, `get_hint` и `check_selection`. Сверка поведения выполнена с `docs/current-state-audit.md`.

## 2. Migrated game package

Игра перенесена в `games/lora_dein/1.0.0/`. Package содержит три сцены, три integer-счетчика и не содержит assets, platform IDs или Python-кода.

Display title версии 1.0.0 — нейтральное «Дело Лоры Дейн»; окончательное продуктовое название остается отдельным решением.

## 3. Preserved behavior

| Legacy behavior | New package behavior | Status |
|---|---|---|
| Scene 1 принимает ровно два ответа; успех только `{1,3}` | `numeric_selection` и `equals: [1,3]` | PRESERVED |
| Восемь достижимых specific feedback для пар с одной правильной уликой | Восемь ordered outcomes с исходными legacy-текстами | PRESERVED |
| Остальные допустимые неверные пары Scene 1 получают generic feedback | Последний `otherwise` outcome | PRESERVED |
| Scene 2 принимает любое правильное подмножество `{1,2,6}` размером 2–3 | `subset_of` с `size.min: 2`, `size.max: 3` | PRESERVED |
| Scene 3 завершается только выбором `6` | `equals: [6]`, затем `complete` | PRESERVED |
| Допустимый неверный ответ увеличивает счетчик своей сцены | `increment wrong_scene1/2/3` | PRESERVED |
| Неверный формат не увеличивает счетчик | Отдельный `when: invalid` без effect | PRESERVED |
| Неверный допустимый ответ повторно показывает сцену | `goto` в ту же scene выполняет `on_enter` | PRESERVED |
| Финал отправляет success, затем thanks | Два ordered `text` action перед `complete` | PRESERVED |

Фактически достижимый success-текст Scene 1 с «дополнительным конвертом №1» выбран каноническим. Недостижимый hint-текст с «вторым конвертом» не переносился.

## 4. Intentional behavior changes

| Legacy behavior | New package behavior | Status |
|---|---|---|
| `re.findall(r"\d+")` извлекает цифры из `1abc3` и `-1` | Принимаются только целые токены и объявленные separators | INTENTIONAL_CHANGE |
| Повторы автоматически превращаются в set | Дубликаты, включая `1,1,3`, дают `invalid: duplicate` | INTENTIONAL_CHANGE |
| Любые нецифровые символы фактически служат разделителями | Разрешены только `comma`, `whitespace`, `word_and` | INTENTIONAL_CHANGE |

## 5. Platform-specific behavior not migrated

| Legacy behavior | New package behavior | Status |
|---|---|---|
| Двухэтапный VK-запуск через название и «Лора» | Package сразу начинается с `lora_scene1` | NOT_GAME_CONCERN |
| «Лора», `/restart`, «рестарт», «заново» сбрасывают игру | Restart остается application use case | NOT_GAME_CONCERN |
| `vk.users.get`, профиль и username игрока | Отсутствуют в package | NOT_GAME_CONCERN |
| Уведомления администраторам и completion report | Отсутствуют в package | NOT_GAME_CONCERN |
| VK Long Poll, heartbeat и logging | Отсутствуют в package | NOT_GAME_CONCERN |

## 6. Characterization coverage

Generic package-test harness исполняет YAML cases через `GameEngine`. Покрыты happy path, все четыре успешных subset Scene 2, четыре отклоненных subset, пять invalid-вводов Scene 2, все восемь достижимых specific feedback Scene 1, generic feedback, все пять неверных убийц, duplicate semantics и три объявленных separator.

## 7. Remaining product questions

1. Утвердить окончательный display title; версия 1.0.0 использует «Дело Лоры Дейн».
2. Утвердить внешние application-тексты меню/restart; в game package они намеренно отсутствуют.
