# Миграция Killing Margo 1.0.0

## 1. Sources

Игровая семантика и тексты извлечены из `killing_margo/tg/main.py` и `killing_margo/vk/main.py` и сверены с `docs/current-state-audit.md`. Значения `QUESTIONS`, `ARTICLES`, `KILLER_NAMES` и `EVIDENCE_LIST` в двух реализациях совпадают.

## 2. Package

Canonical package находится в `games/killing_margo/1.0.0/`. Он не содержит platform API, callback data, внешних attachment IDs или game-specific Python. Display title версии — «Убийство Марго».

## 3. Canonical flow

`Q1 → Q2 → Q3 → Q4 → safe → Q5 → Q6 → Q7 → Q8 → Q9 → phone recording → articles → killer → complete`.

Q1–Q7 используют отдельные generic choice scenes для подсказок. Q8 и Q9 не имеют подсказок. Safe является отдельной scene. Articles доступны сразу после Q9.

## 4. Preserved behavior

- Сохранены все prompts, success/wrong/partial responses и содержательные hints.
- Q4, Q6 и Q9 проверяют неупорядоченные точные пары и дают partial response при пересечении размером один.
- Safe открывается кодом `1503`; ручной ввод «Подсказка» показывает существующий legacy hint.
- Сохранены все 11 названий и полных текстов статей.
- Сохранены шесть killer aliases, финальный success и полицейский отчет.
- Outcome actions всегда предшествуют `on_enter` следующей scene.

## 5. Intentional changes

- Q2 принимает ровно одну улику `11`; `11,999` и `11,abc` больше не проходят.
- Numeric parser не извлекает встроенные цифры, запрещает дубликаты и проверяет declared separators/cardinality/range.
- Text answers используют explicit equality aliases после normalization, а не случайное substring matching.
- Stale hint/article choices адресуются interaction и revision средствами общего engine.

## 6. TG/VK drift resolution

| Legacy difference | Canonical behavior | Reason |
|---|---|---|
| TG `/start` сбрасывает игру; VK требует codeword | Запуск/restart отсутствуют в package | Application concern |
| VK hints после safe смещены на один вопрос | Каждая hint scene возвращает к своему вопросу | Подтвержденный VK bug |
| TG принимает `и`, VK evidence pairs — только запятую | `comma`, `whitespace`, `word_and` для всех numeric pairs | Единая межплатформенная семантика |
| TG delay 300 секунд, VK delay 5 секунд | Ровно 300 секунд | Утвержденное canonical значение |
| TG показывает article buttons, VK принимает номер | Один semantic `read_article` interaction поддерживает text и choice | Rendering является adapter concern |
| TG/VK по-разному доставляют media | Четыре semantic media ID | Platform delivery является adapter concern |
| Q2 проверяет только первый numeric token | Ровно одна улика `11` | Устранение accidental permissiveness |
| Named answers проходили по substring | Explicit aliases | Предсказуемый schema v1 matching |
| Q4/Q6/Q9 partial text использует «значений» в TG и «чисел» в VK | Использован TG-текст «значений» | Совпадает с утвержденным DSL draft |

## 7. Matching changes

Q1/Q8 принимают только aliases `нет` и `не`. Q3, Q7 и killer используют полные списки legacy aliases. Q5 перечисляет canonical comma/`и` permutations через существующий `aliases`; новый parser не добавлялся.

## 8. Hints

Восемь hint flows реализованы generic choice scenes: Q1–Q7 и killer. `yes` отправляет соответствующий hint перед повторным prompt; `no` отправляет legacy decline перед prompt. `hint_yes`, `hint_no`, Telegram/VK keyboard objects и dead sentinel `99` не переносились.

Safe hint сохранен как прямой text outcome на фактически поддерживаемый ввод «Подсказка», без sentinel или отдельного platform callback.

## 9. Articles

`margo_articles` содержит exact readiness interaction и numeric `read_article` interaction 1–11. Каждый article outcome отправляет полный legacy-текст и follow-up, остается в той же scene и доступен как через `TextInput`, так и через semantic `ChoiceInput`.

## 10. Scheduled reveal

Q9 планирует `reveal_articles` на `now + 300 seconds`. Guard требует `status=in_progress` и `current_scene=margo_articles`. Reveal отправляет legacy reminder и semantic choices со всеми 11 titles; это список, а не unlock-флаг.

## 11. Media mapping + hashes

TG/VK пары имеют одинаковые размеры и SHA-256. Package files скопированы без перекодирования и совпадают с source.

| Semantic ID | Package path | Bytes | SHA-256 |
|---|---|---:|---|
| `safe_closed` | `assets/safe_closed.jpg` | 284882 | `11117e0467e3af10625e6431746b089c2c79d8b91152448434dea3d0b87775b2` |
| `safe_open` | `assets/safe_open.jpg` | 1162362 | `a1893dab36b8f12458e7fe860e57b0ff2ea9028d6a868ac1f0ed564bd2637110` |
| `phone_recording` | `assets/phone_recording.mp3` | 1932520 | `891b7265128f9b67cc183d66730ac6a8f7331aa3c9ebdc721d8ad1cadf5bc117` |
| `final_police_report` | `assets/final_police_report.jpg` | 383921 | `75cc5e1e6039a56d78b17bab5195ab6f7aada4dc1554d1c493afe3e033353a9a` |

## 12. Characterization coverage

Generic package tests покрывают полный happy path, wrong Q1–Q9, yes/no каждого hint flow, три partial pair outcome, все invalid reasons, три pair separators, safe success/wrong/hint, все 11 статей с exact content, semantic article choice, readiness normalization, schedule `+300s`, все killer aliases и deterministic action ordering.

## 13. Remaining questions

1. Окончательно утвердить display title: package использует «Убийство Марго», legacy VK runtime — «Убийственная Маргарита».
2. Определить presentation hint для финального JPG на каждой платформе (document в TG или image в VK); package хранит semantic image asset.
3. Утвердить application-level menu/restart/post-completion тексты.
