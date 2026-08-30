# Проект формата game package

Статус: конкретный draft этапа 2, не окончательная схема.  
Связанная архитектура: `docs/target-architecture.md`.  
Примеры ниже предназначены для проверки выразительности формата, а не для немедленной миграции контента.

## 1. Цели дизайна

Формат должен:

1. одинаково исполняться через Telegram и VK;
2. выразить все подтвержденные механики `killing_margo` и `lora_dein` без game-specific Python;
3. быть читаемым автором игры и строго валидируемым до запуска;
4. явно задавать parsing/matching вместо неявных эвристик;
5. ссылаться на semantic media IDs, а не platform IDs;
6. поддерживать immutable version, pinned к сессии;
7. позволять unit/characterization tests без сети и БД;
8. оставаться небольшим форматом для линейных игр с ограниченным ветвлением.

## 2. Не-цели

В draft намеренно отсутствуют:

- arbitrary Python, Jinja, expression strings или `eval`;
- fuzzy/LLM/semantic matching;
- regex: текущим утвержденным требованиям он не нужен;
- скриптовые плагины конкретной игры;
- inventory, Fact, achievements, scoring, NPC и multiplayer;
- универсальные workflows, parallel branches и subroutines;
- встроенная локализационная система;
- Telegram callback data, VK payload и типы keyboard;
- SQL/persistence declarations;
- CDN и удаленные media URLs как обязательный источник.

## 3. Структура game package

```text
games/
  killing_margo/
    1.0.0/
      manifest.yaml
      game.yaml
      assets/
        safe_closed.jpg
        safe_open.jpg
        phone_recording.mp3
        final_police_report.jpg
      tests/
        happy_path.yaml
        pair_partial.yaml
        articles.yaml
  lora_dein/
    1.0.0/
      manifest.yaml
      game.yaml
      assets/
      tests/
        happy_path.yaml
        scene1_feedback.yaml
        scene2_subsets.yaml
```

Путь `<game_id>/<version>` нужен для одновременного хранения старых и новых immutable versions. Package включает только одну игру и одну версию.

## 4. `manifest.yaml`

Manifest отвечает за каталог и упаковку, а не за game flow:

```yaml
schema_version: 1
game_id: killing_margo
version: 1.0.0
display_title: "Убийство Марго"
description: "Интерактивное дополнение к физической игре-детективу."
language: ru
game_file: game.yaml

assets:
  safe_closed:
    type: image
    path: assets/safe_closed.jpg
  safe_open:
    type: image
    path: assets/safe_open.jpg
  phone_recording:
    type: audio
    path: assets/phone_recording.mp3
  final_police_report:
    type: image
    path: assets/final_police_report.jpg
```

### Семантика полей

| Поле | Назначение |
|---|---|
| `schema_version` | версия самого формата loader/validator |
| `game_id` | стабильный machine ID игры |
| `version` | immutable версия контента и правил, SemVer-подобная |
| `display_title` | название в application menu |
| `description` | краткое описание каталога |
| `language` | язык текущего монолингвального package |
| `game_file` | относительный путь к runtime definition |
| `assets` | semantic asset ID → тип и локальный путь |

Immutable version manifest не содержит `enabled` или другой mutable availability-флаг. Filesystem catalog этапа 3 считает все найденные валидные packages установленными и выбирает наибольшую SemVer только по явному вызову `get_latest`. Будущая product availability является application/catalog concern вне version package.

### Почему manifest отделен от `game.yaml`

Catalog может прочитать маленький manifest, не загружая большой граф сцен. Asset integrity и package identity проверяются отдельно от исполнения. `game.yaml` при этом не дублирует `game_id`, `version`, title и asset paths.

## 5. `game.yaml`

Корневая структура:

```yaml
schema_version: 1
entry_scene: margo_q1

variables:
  example_flag:
    type: boolean
    default: false
  example_counter:
    type: integer
    default: 0
  example_label:
    type: string
    default: ""

scheduled_actions: {}
scenes: {}
```

Текущим играм достаточно типов `boolean`, `integer`, `string`. Timestamp не вводится как session variable: `due_at`, attempts и lease — инфраструктурные поля durable scheduled action. Если будущая подтвержденная game rule должна сравнивать игровое время, тип можно добавить новой `schema_version`.

`safe_opened` не переносится: закрытый сейф и вопрос после открытия становятся разными scenes. Pending hint также не переменная: текущая hint scene однозначно описывает ожидаемый выбор.

## 6. Основные примитивы

1. `GameDefinition` — `entry_scene`, variables, scheduled templates и scenes.
2. `Scene` — ordered `on_enter`, один или несколько interactions, fallback.
3. `InputSpec` — явный parser/normalizer neutral input.
4. `OutcomeRule` — именованное декларативное условие, actions, effects и transition.
5. `OutputAction` — `text`, `media`, `choices`.
6. `Effect` — `set`, `increment`, `schedule`.
7. `Transition` — `stay`, `goto`, `complete`.
8. `ScheduledActionTemplate` — guard и semantic outputs для durable delivery.
9. `SessionVariable` — типизированное значение конкретной сессии.

Отдельные `Fact`, `Condition` hierarchy, `Response` и `Trigger` classes не нужны: условие находится в `OutcomeRule`, а semantic outputs — в его `actions`.

## 7. `Scene`

```yaml
scenes:
  example:
    on_enter:
      - type: text
        text: "Вопрос игроку"

    interactions:
      - id: answer
        input:
          type: text
          normalize: [trim, lowercase]
        outcomes:
          - id: correct
            when:
              match:
                strategy: aliases
                values: ["вариант а", "полный вариант а"]
            actions:
              - type: text
                text: "Верно"
            transition:
              goto: next_scene

          - id: wrong
            when: otherwise
            actions:
              - type: text
                text: "Неверно"
            transition: stay

    fallback:
      actions:
        - type: text
          text: "Используйте текстовый ответ."
      transition: stay
```

Правила:

- `on_enter` выполняется по порядку при первом входе и при любом `goto`, включая `goto` в ту же scene.
- `stay` сохраняет текущую scene и **не** повторяет `on_enter`.
- `goto: same_scene` повторно входит и выполняет `on_enter`; это покрывает Lora repeat-question.
- interactions проверяются в записанном порядке.
- Для semantic callback adapter передает `interaction_id` и value прямо; для текста engine ищет подходящий interaction.
- Если InputSpec разобрал текст, но ни один outcome не совпал и `otherwise` отсутствует, engine продолжает со следующим interaction. Это позволяет сначала проверить exact readiness phrase, затем numeric article input.
- Semantic callback адресуется только указанному `interaction_id`; engine не пробует другие interactions и проверяет, что choice относится к текущей scene/revision.
- Если ни один interaction не принял input, выполняется scene `fallback`.

## 8. `InputSpec`

### 8.1 Text

```yaml
input:
  type: text
  normalize: [trim, lowercase]
```

Поддерживаемые normalization steps в schema v1:

- `trim`;
- `lowercase`;
- `collapse_whitespace`;
- `replace_yo` — только если автор явно хочет считать `ё` и `е` одинаковыми.

### 8.2 Numeric selection

```yaml
input:
  type: numeric_selection
  separators: [comma, whitespace, word_and]
  unique: true
  min_items: 2
  max_items: 2
  allowed_values: [1, 2, 3, 4, 5, 6]
```

Parser принимает только целые токены и перечисленные разделители; он не извлекает случайные цифры из произвольных слов. Результат — множество уникальных integers.

В schema v1 `unique` обязан быть `true`, а `min_items` и `max_items` — целые числа не меньше `1`: пустой numeric selection не поддерживается. Повтор значения является `invalid` с причиной `duplicate`. Например, `1,1,3` не преобразуется в `{1,3}`.

Результаты parsing:

- `valid` — можно проверять selection predicates;
- `invalid` с машинной причиной `empty`, `syntax`, `duplicate`, `too_few`, `too_many`, `out_of_range`;
- `no_match` — input явно не похож на этот тип и следующий interaction может его обработать.

В scene с одним numeric interaction и `no_match` fallback обычно показывает то же сообщение формата.

### 8.3 Semantic choice

```yaml
input:
  type: choice
  options:
    "yes":
      label: "Да"
      text_aliases: ["да"]
    "no":
      label: "Нет"
      text_aliases: ["нет"]
```

Adapter преобразует кнопку в semantic value `yes`/`no`. Typed text может использовать `text_aliases`. Platform payload формируется adapter и отсутствует в YAML.

Реализация допускает semantic value типа `string` или `integer`; integer обычно используется `ChoiceInput` для адресованного numeric interaction, например кнопки статьи. Для typed aliases применяется только явно объявленный `normalize` pipeline самого choice InputSpec.

Поле `ChoiceInput.session_revision` остается nullable на transport-модели, чтобы отсутствие revision можно было представить и классифицировать, но pure engine отклоняет такой semantic choice как stale. Ручной текстовый выбор проходит через `TextInput` и `text_aliases`.

### 8.4 Match strategies в outcome

- `exact` — нормализованная строка равна одному `value`;
- `aliases` — равна одному элементу `values`;
- `contains` — содержит одну из явно заданных строк; применяется только осознанно;
- numeric selection predicates — над разобранным множеством.

`aliases` означает равенство alias, а не substring. Это устраняет legacy-дефект, где `не` совпадало с любым словом.

## 9. `OutputAction`

### Text

```yaml
- type: text
  text: "Сообщение игроку"
```

### Media

```yaml
- type: media
  asset: safe_closed
  caption: "Вы находите закрытый сейф."
```

Тип (`image`, `audio`, `document`) берется из manifest. Опциональный `render_as: document` допустим только как semantic presentation hint, одинаковый для платформ; platform API object запрещен. В MVP лучше использовать естественный тип asset.

### Choices

```yaml
- type: choices
  interaction: hint_decision
  text: "Друг, тебе нужна подсказка?"
```

Для `input.type: choice` labels/options по умолчанию берутся из `InputSpec` указанного interaction. Для numeric selection, как в списке статей, action явно задает отображаемые варианты:

```yaml
- type: choices
  interaction: read_article
  text: "Выбери статью:"
  options:
    - {value: 1, label: "1. Частные клиники"}
    - {value: 2, label: "2. Раздел имущества"}
```

Каждый `value` должен быть допустим для целевого InputSpec. Telegram adapter может отобразить inline buttons, VK — callback keyboard/payload или текстовые buttons. Engine видит только semantic values.

### Почему delayed output не является обычным `OutputAction`

Сами будущие сообщения остаются `OutputAction`, но момент доставки — эффект `schedule`, который создает durable record. Если вложить `delay_seconds` непосредственно в любую action, lifecycle, idempotency и guard станут неявными. Поэтому schedule отделен от рендеринга.

## 10. `OutcomeRule`

Outcome rules проверяются сверху вниз; первый match завершает обработку interaction.

Поддерживаемые условия schema v1:

```yaml
when: invalid
when: otherwise
when:
  choice: "yes"
when:
  match:
    strategy: exact
    value: "1503"
when:
  match:
    strategy: aliases
    values: ["лео", "лео миллер"]
when:
  match:
    strategy: contains
    values: ["явно заданная подстрока"]
when:
  selection:
    equals: [1, 3]
when:
  selection:
    subset_of: [1, 2, 6]
    size:
      min: 2
      max: 3
when:
  selection:
    intersection_with: [11, 17]
    intersection_size: 1
```

Никаких строковых логических выражений нет. Validator проверяет shape каждого оператора.

`invalid` — ошибка parsing/формата. `otherwise` обязан быть последним в interaction. Specific-combination rules размещаются перед общими partial/wrong.

## 11. `Transition`

Transition остается inline-полем outcome, а не отдельной сущностью:

```yaml
transition: stay
transition:
  goto: margo_q4
transition: complete
```

Этого достаточно текущим играм:

- `stay` — не менять scene и не выполнять `on_enter`;
- `goto` — сменить/повторно войти в scene и выполнить ее `on_enter`;
- `complete` — установить session status `completed`, `completed_at`, отменить несовместимые pending actions.

Отдельный объект/registry переходов добавил бы косвенность без повторного использования.

## 12. Session variables и Effects

### Variables

```yaml
variables:
  wrong_scene1:
    type: integer
    default: 0
```

Engine валидирует тип при каждом effect.

### Effects

```yaml
effects:
  - type: set
    variable: example_flag
    value: true

  - type: increment
    variable: wrong_scene1
    by: 1

  - type: schedule
    action: reveal_articles
    delay_seconds: 300
    idempotency_key: reveal_articles
```

`reset/restart` не является game effect: согласно продуктовой политике это явный application use case с подтверждением, созданием новой session и отменой pending actions старой. `complete` представлен transition, чтобы не допускать противоречия `effect complete + goto`.

Schedule metadata (`due_at`, attempts, lease, status) хранится infrastructure, а не в `variables`.

## 13. Подсказки

Выбран минимальный generic semantic `choice` в отдельной короткой scene. Специального `Hint` primitive нет.

```yaml
scenes:
  margo_q3_hint:
    on_enter:
      - type: choices
        interaction: hint_decision
        text: "Друг, тебе нужна подсказка?"

    interactions:
      - id: hint_decision
        input:
          type: choice
          options:
            "yes":
              label: "Да"
              text_aliases: ["да"]
            "no":
              label: "Нет"
              text_aliases: ["нет"]
        outcomes:
          - id: show_hint
            when:
              choice: "yes"
            actions:
              - type: text
                text: "Кажется, только этот человек носил такой размер обуви."
            transition:
              goto: margo_q3

          - id: decline_hint
            when:
              choice: "no"
            actions:
              - type: text
                text: "Хорошо, попробуй еще раз."
            transition:
              goto: margo_q3
```

Game semantics полностью видна: предложить, yes/no, показать hint, вернуться и повторить prompt через `on_enter`. Telegram/VK callback details отсутствуют. Тот же `choice` пригоден для любых подтверждений; более универсальный Interaction framework не нужен.

## 14. Статьи и secondary interactions

Article mode — одна scene с двумя независимыми interactions:

1. exact readiness phrase меняет scene;
2. numeric selection 1..11 отправляет соответствующий текст и остается;
3. semantic article buttons направляются тому же `read_article` interaction.

Это не knowledge-base engine: каждая статья — обычный outcome с text action.

```yaml
scenes:
  margo_articles:
    interactions:
      - id: ready_to_name_killer
        input:
          type: text
          normalize: [trim, lowercase, collapse_whitespace]
        outcomes:
          - id: ready
            when:
              match:
                strategy: exact
                value: "готов назвать убийцу"
            actions:
              - type: text
                text: "Я в предвкушении! Итак, удиви меня!"
            transition:
              goto: margo_killer

      - id: read_article
        input:
          type: numeric_selection
          separators: [comma, whitespace]
          unique: true
          min_items: 1
          max_items: 1
          allowed_values: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        outcomes:
          - id: article_3
            when:
              selection:
                equals: [3]
            actions:
              - type: text
                text: "Полный текст статьи 3 из game content."
            transition: stay
          # Аналогичные явные rules существуют для 1..11.

    fallback:
      actions:
        - type: text
          text: "Выбери статью 1–11 или напиши «Готов назвать убийцу»."
      transition: stay
```

Строка `"3"` разбирается `read_article`; semantic button сразу указывает `interaction=read_article, value=3`. Readiness interaction стоит раньше, поэтому точная фраза не попадает в numeric parsing.

## 15. Отложенные действия

```yaml
scheduled_actions:
  reveal_articles:
    guard:
      session_status: in_progress
      current_scene: margo_articles
    actions:
      - type: text
        text: "Кстати, чуть не забыл! У меня есть еще одна улика."
      - type: choices
        interaction: read_article
        text: "Я нашел историю посещений веб-страниц. Выбери статью:"
        options:
          - {value: 1, label: "1. Частные клиники"}
          - {value: 2, label: "2. Раздел имущества"}
          - {value: 3, label: "3. Причины развода"}
          - {value: 4, label: "4. Домашнее насилие"}
          - {value: 5, label: "5. Доказательство домогательств"}
          - {value: 6, label: "6. Jacob Adams Oakville 2016"}
          - {value: 7, label: "7. Условно-досрочное освобождение"}
          - {value: 8, label: "8. Рецепт пиццы"}
          - {value: 9, label: "9. Прогноз матча"}
          - {value: 10, label: "10. Подлинность рецепта"}
          - {value: 11, label: "11. Отслеживание заказа"}
```

Scene schedule:

```yaml
effects:
  - type: schedule
    action: reveal_articles
    delay_seconds: 300
    idempotency_key: reveal_articles
```

DSL описывает semantic intent. Application вычисляет `due_at` от переданного engine clock, связывает действие с session/version/revision и транзакционно сохраняет его в PostgreSQL. Guard предотвращает сообщение старой/restarted/completed сессии и, согласно выбранному draft, отменяет reveal, если игрок уже покинул article scene.

## 16. Media assets

Правила:

1. `asset` обязан существовать в `manifest.assets`.
2. `path` относителен package root, не CWD.
3. После нормализации путь не может выходить из package.
4. Тип должен быть одним из `image`, `audio`, `document`, `video`; текущие игры используют первые три.
5. Telegram `file_id` и VK attachment ID хранятся только в infrastructure media cache.
6. Cache key включает platform, bot identity, game ID/version, asset ID и digest файла.
7. Отсутствующий обязательный файл — validation ERROR.

Margo использует:

```yaml
- type: media
  asset: safe_closed
- type: media
  asset: safe_open
- type: media
  asset: phone_recording
- type: media
  asset: final_police_report
```

## 17. Подробный draft YAML: значимые механики Margo

Ниже один согласованный фрагмент package. Длинные тексты статей сокращены, но все маршруты и механики заданы явно.

### `manifest.yaml`

```yaml
schema_version: 1
game_id: killing_margo
version: 1.0.0
display_title: "Убийство Марго"
description: "Расследование убийства Елены Миллер."
language: ru
game_file: game.yaml
assets:
  safe_closed: {type: image, path: assets/safe_closed.jpg}
  safe_open: {type: image, path: assets/safe_open.jpg}
  phone_recording: {type: audio, path: assets/phone_recording.mp3}
  final_police_report: {type: image, path: assets/final_police_report.jpg}
```

### `game.yaml`

```yaml
schema_version: 1
entry_scene: margo_q3
variables: {}

scheduled_actions:
  reveal_articles:
    guard:
      session_status: in_progress
      current_scene: margo_articles
    actions:
      - type: text
        text: |
          Кстати, чуть не забыл! У меня же есть для тебя еще одна улика.
          Я нашел историю посещений веб-страниц Елены.
      - type: choices
        interaction: read_article
        text: "Выбери статью:"
        options:
          - {value: 1, label: "1. Частные клиники лечения игровой зависимости"}
          - {value: 2, label: "2. Раздел имущества при разводе"}
          - {value: 3, label: "3. Причины развода и смерть супруга"}
          - {value: 4, label: "4. Домашнее насилие"}
          - {value: 5, label: "5. Доказательство домогательств"}
          - {value: 6, label: "6. Jacob Adams Oakville 2016"}
          - {value: 7, label: "7. Условно-досрочное освобождение"}
          - {value: 8, label: "8. Рецепт пиццы"}
          - {value: 9, label: "9. Прогноз футбольного матча"}
          - {value: 10, label: "10. Подлинность рецептурного бланка"}
          - {value: 11, label: "11. Отслеживание заказа пиццы"}

scenes:
  # A. Обычный вопрос с aliases.
  margo_q3:
    on_enter:
      - type: text
        text: "Ты уже должен был догадаться, кто это. Напиши имя этого человека."
    interactions:
      - id: answer
        input:
          type: text
          normalize: [trim, lowercase, collapse_whitespace, replace_yo]
        outcomes:
          - id: correct_leo
            when:
              match:
                strategy: aliases
                values:
                  - "лео"
                  - "лео миллер"
                  - "брат елены"
                  - "еленин брат"
            actions:
              - type: text
                text: "Твои дедуктивные способности поразительны!"
            transition:
              goto: margo_q4
          - id: wrong
            when: otherwise
            actions:
              - type: text
                text: "Кандидат слабоват. Кто еще у тебя на примете?"
            transition:
              goto: margo_q3_hint

  # E. Hint Да/Нет как semantic choice.
  margo_q3_hint:
    on_enter:
      - type: choices
        interaction: hint_decision
        text: "Друг, тебе нужна подсказка?"
    interactions:
      - id: hint_decision
        input:
          type: choice
          options:
            "yes": {label: "Да", text_aliases: ["да"]}
            "no": {label: "Нет", text_aliases: ["нет"]}
        outcomes:
          - id: yes
            when: {choice: "yes"}
            actions:
              - type: text
                text: "Кажется, только этот человек носил такой размер обуви."
            transition: {goto: margo_q3}
          - id: no
            when: {choice: "no"}
            actions:
              - type: text
                text: "Хорошо, попробуй еще раз."
            transition: {goto: margo_q3}

  # B/C. Точная неупорядоченная пара и partial.
  margo_q4:
    on_enter:
      - type: text
        text: "Какие 2 улики это доказывают? Напиши номера улик."
    interactions:
      - id: evidence_pair
        input:
          type: numeric_selection
          separators: [comma, whitespace, word_and]
          unique: true
          min_items: 2
          max_items: 2
          allowed_values:
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
             11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
             21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
             31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41]
        outcomes:
          - id: invalid_format
            when: invalid
            actions:
              - type: text
                text: "Укажи ровно два номера улик."
            transition: stay
          - id: correct_pair
            when:
              selection:
                equals: [11, 17]
            actions:
              - type: text
                text: "Отлично! Наконец-то мы разобрались с братом жертвы."
            transition:
              goto: margo_safe
          - id: one_correct
            when:
              selection:
                intersection_with: [11, 17]
                intersection_size: 1
            actions:
              - type: text
                text: "Одно из значений верно, но второе — нет. Попробуй снова."
            transition: stay
          - id: wrong_pair
            when: otherwise
            actions:
              - type: text
                text: "Неверно. Давай еще раз."
            transition: stay

  # D/J. Отдельная scene сейфа устраняет safe_opened.
  margo_safe:
    on_enter:
      - type: media
        asset: safe_closed
        caption: "Вы находите сейф. Введите код из четырех цифр."
    interactions:
      - id: safe_code
        input:
          type: text
          normalize: [trim]
        outcomes:
          - id: opened
            when:
              match:
                strategy: exact
                value: "1503"
            actions:
              - type: media
                asset: safe_open
                caption: "Щелчок! Сейф открыт."
            transition:
              goto: margo_q5
          - id: wrong_code
            when: otherwise
            actions:
              - type: text
                text: "Неверный код. Сейф не открывается."
            transition: stay

  margo_q5:
    on_enter:
      - type: text
        text: "Назови двух людей, которые врут в допросах."
    interactions:
      - id: answer
        input:
          type: text
          normalize: [trim, lowercase, collapse_whitespace]
        outcomes:
          - id: accepted_names
            when:
              match:
                strategy: aliases
                values:
                  - "виктор, джулиан"
                  - "джулиан, виктор"
                  - "виктор браун, джулиан эванс"
                  - "джулиан эванс, виктор браун"
            actions:
              - type: text
                text: "Да ты чертов гений!"
            transition:
              goto: margo_q9
          - id: wrong
            when: otherwise
            actions:
              - type: text
                text: "Давай по новой."
            transition: stay

  # F/J. После финального вопроса — audio и durable schedule 300s.
  margo_q9:
    on_enter:
      - type: text
        text: "Какие 2 улики доказывают, что Оливия не могла убить Елену?"
    interactions:
      - id: evidence_pair
        input:
          type: numeric_selection
          separators: [comma, whitespace, word_and]
          unique: true
          min_items: 2
          max_items: 2
          allowed_values:
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
             11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
             21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
             31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41]
        outcomes:
          - id: correct
            when:
              selection:
                equals: [31, 33]
            actions:
              - type: text
                text: "Открывай последний конверт. Сразу присылаю одну улику."
              - type: media
                asset: phone_recording
            effects:
              - type: schedule
                action: reveal_articles
                delay_seconds: 300
                idempotency_key: reveal_articles
            transition:
              goto: margo_articles
          - id: partial
            when:
              selection:
                intersection_with: [31, 33]
                intersection_size: 1
            actions:
              - type: text
                text: "Одна улика верна, но вторая — нет."
            transition: stay
          - id: wrong
            when: otherwise
            actions:
              - type: text
                text: "Неверно. Попробуй еще раз."
            transition: stay

  # G/H. 11 непродвигающих article routes и exact exit.
  margo_articles:
    interactions:
      - id: ready_to_name_killer
        input:
          type: text
          normalize: [trim, lowercase, collapse_whitespace]
        outcomes:
          - id: ready
            when:
              match:
                strategy: exact
                value: "готов назвать убийцу"
            actions:
              - type: text
                text: "Я в предвкушении! Итак, удиви меня!"
            transition:
              goto: margo_killer

      - id: read_article
        input:
          type: numeric_selection
          separators: [comma, whitespace]
          unique: true
          min_items: 1
          max_items: 1
          allowed_values: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        outcomes:
          - {id: article_1, when: {selection: {equals: [1]}}, actions: [{type: text, text: "Полный текст статьи 1."}], transition: stay}
          - {id: article_2, when: {selection: {equals: [2]}}, actions: [{type: text, text: "Полный текст статьи 2."}], transition: stay}
          - {id: article_3, when: {selection: {equals: [3]}}, actions: [{type: text, text: "Полный текст статьи 3."}], transition: stay}
          - {id: article_4, when: {selection: {equals: [4]}}, actions: [{type: text, text: "Полный текст статьи 4."}], transition: stay}
          - {id: article_5, when: {selection: {equals: [5]}}, actions: [{type: text, text: "Полный текст статьи 5."}], transition: stay}
          - {id: article_6, when: {selection: {equals: [6]}}, actions: [{type: text, text: "Полный текст статьи 6."}], transition: stay}
          - {id: article_7, when: {selection: {equals: [7]}}, actions: [{type: text, text: "Полный текст статьи 7."}], transition: stay}
          - {id: article_8, when: {selection: {equals: [8]}}, actions: [{type: text, text: "Полный текст статьи 8."}], transition: stay}
          - {id: article_9, when: {selection: {equals: [9]}}, actions: [{type: text, text: "Полный текст статьи 9."}], transition: stay}
          - {id: article_10, when: {selection: {equals: [10]}}, actions: [{type: text, text: "Полный текст статьи 10."}], transition: stay}
          - {id: article_11, when: {selection: {equals: [11]}}, actions: [{type: text, text: "Полный текст статьи 11."}], transition: stay}
    fallback:
      actions:
        - type: text
          text: "Выбери статью 1–11 или напиши «Готов назвать убийцу»."
      transition: stay

  # I/J. Финальные aliases, media и complete.
  margo_killer:
    on_enter:
      - type: text
        text: "Назови убийцу."
    interactions:
      - id: answer
        input:
          type: text
          normalize: [trim, lowercase, collapse_whitespace, replace_yo]
        outcomes:
          - id: correct
            when:
              match:
                strategy: aliases
                values:
                  - "марк"
                  - "марк дэвис"
                  - "марк девис"
                  - "джейкоб"
                  - "джейкоб адамс"
                  - "адамс"
            actions:
              - type: text
                text: "Ты вычислил убийцу. Отправляю полицейский отчет."
              - type: media
                asset: final_police_report
            transition: complete
          - id: wrong
            when: otherwise
            actions:
              - type: text
                text: "Кажется, ты планируешь посадить невиновного?"
            transition: stay
```

Пример начинает с Q3 только для компактности. В полном package `entry_scene` будет реальной первой scene, а В1–В9 свяжутся последовательно; показанные fragments доказывают выразимость всех обязательных механик.

Замечание о В5: draft выше сохраняет перечисленные legacy-фразы как aliases. Более естественное моделирование имен как unordered text selection потребовало бы нового parser, который пока не нужен другим утвержденным требованиям; при миграции можно либо оставить явные aliases, либо обосновать небольшой `token_selection` extension.

## 18. Полный draft YAML: все механики Lora

### `manifest.yaml`

```yaml
schema_version: 1
game_id: lora_dein
version: 1.0.0
display_title: "Дело Лоры Дейн"
description: "Расследование убийства актрисы Лоры Дейн."
language: ru
game_file: game.yaml
assets: {}
```

### `game.yaml`

```yaml
schema_version: 1
entry_scene: lora_scene1

variables:
  wrong_scene1: {type: integer, default: 0}
  wrong_scene2: {type: integer, default: 0}
  wrong_scene3: {type: integer, default: 0}

scheduled_actions: {}

scenes:
  # A. Ровно два ответа; success {1,3}; combination feedback; count; repeat.
  lora_scene1:
    on_enter:
      - type: text
        text: |
          Томми Вайс обвиняется в убийстве Лоры Дейн.
          Найдите 2 улики, доказывающие его невиновность:
          1. Томми был в баре Golden Lion в момент убийства
          2. Размер обуви Томми не совпадает
          3. Томми завтракал с Лорой во время прохода по ее пропуску
          4. Крысиный яд был куплен по просьбе Лоры
          5. Томми работал на другой студии
          6. Томми не знал об изменах Лоры
    interactions:
      - id: choose_evidence
        input:
          type: numeric_selection
          separators: [comma, whitespace, word_and]
          unique: true
          min_items: 2
          max_items: 2
          allowed_values: [1, 2, 3, 4, 5, 6]
        outcomes:
          - id: invalid_format
            when: invalid
            actions:
              - type: text
                text: "Введите ровно два разных номера от 1 до 6."
            transition: stay

          - id: success_1_3
            when: {selection: {equals: [1, 3]}}
            actions:
              - type: text
                text: "Вам удалось оправдать невиновного! Открывайте дополнительный конверт №1."
            transition: {goto: lora_scene2}

          - id: feedback_1_2
            when: {selection: {equals: [1, 2]}}
            actions:
              - type: text
                text: "Алиби в баре верно, но след обуви нельзя уверенно считать следом убийцы."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}
          - id: feedback_2_3
            when: {selection: {equals: [2, 3]}}
            actions:
              - type: text
                text: "Завтрак и пропуск верны, но размер обуви не доказывает невиновность."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}
          - id: feedback_1_4
            when: {selection: {equals: [1, 4]}}
            actions:
              - type: text
                text: "Алиби верно, но без судмедэкспертизы яд не доказывает причину смерти."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}
          - id: feedback_3_4
            when: {selection: {equals: [3, 4]}}
            actions:
              - type: text
                text: "Завтрак и пропуск верны, но версия с ядом не доказана."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}
          - id: feedback_1_5
            when: {selection: {equals: [1, 5]}}
            actions:
              - type: text
                text: "Алиби верно, но работа на другой студии не исключает проникновение."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}
          - id: feedback_3_5
            when: {selection: {equals: [3, 5]}}
            actions:
              - type: text
                text: "Завтрак и пропуск верны, но другая студия не исключает доступ в другое время."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}
          - id: feedback_1_6
            when: {selection: {equals: [1, 6]}}
            actions:
              - type: text
                text: "Алиби верно, но отсутствие известного мотива не является оправдывающей уликой."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}
          - id: feedback_3_6
            when: {selection: {equals: [3, 6]}}
            actions:
              - type: text
                text: "Завтрак и пропуск верны, но отсутствие мотива недостаточно."
            effects: [{type: increment, variable: wrong_scene1, by: 1}]
            transition: {goto: lora_scene1}

          - id: other_wrong_pair
            when: otherwise
            actions:
              - type: text
                text: "Нужно найти две настоящие улики. Попробуйте еще раз."
            effects:
              - type: increment
                variable: wrong_scene1
                by: 1
            transition:
              goto: lora_scene1

  # B. Только {1,2,6}, минимум 2, максимум 3, никаких wrong items.
  lora_scene2:
    on_enter:
      - type: text
        text: |
          Найдите подозреваемых с мотивом:
          1. Рита Морган
          2. Ван Ли
          3. Винсент Кроули
          4. Карл Брукс
          5. Томми Вайс
          6. Глория Фэрроу
    interactions:
      - id: choose_suspects
        input:
          type: numeric_selection
          separators: [comma, whitespace, word_and]
          unique: true
          min_items: 2
          max_items: 3
          allowed_values: [1, 2, 3, 4, 5, 6]
        outcomes:
          - id: invalid_format
            when: invalid
            actions:
              - type: text
                text: "Выберите от двух до трех разных номеров 1–6."
            transition: stay
          - id: valid_correct_subset
            when:
              selection:
                subset_of: [1, 2, 6]
                size: {min: 2, max: 3}
            actions:
              - type: text
                text: "Вам удалось найти подозреваемых! Открывайте дополнительный конверт №2."
            transition:
              goto: lora_scene3
          - id: contains_wrong_suspect
            when: otherwise
            actions:
              - type: text
                text: "Нужно найти настоящих подозреваемых. Попробуйте еще раз."
            effects:
              - type: increment
                variable: wrong_scene2
                by: 1
            transition:
              goto: lora_scene2

  # C. Ровно один; success 6; complete.
  lora_scene3:
    on_enter:
      - type: text
        text: |
          Кто убил Лору Дейн?
          1. Рита Морган
          2. Ван Ли
          3. Винсент Кроули
          4. Карл Брукс
          5. Томми Вайс
          6. Глория Фэрроу
    interactions:
      - id: choose_killer
        input:
          type: numeric_selection
          separators: [comma, whitespace]
          unique: true
          min_items: 1
          max_items: 1
          allowed_values: [1, 2, 3, 4, 5, 6]
        outcomes:
          - id: invalid_format
            when: invalid
            actions:
              - type: text
                text: "Введите один номер от 1 до 6."
            transition: stay
          - id: gloria
            when: {selection: {equals: [6]}}
            actions:
              - type: text
                text: "Вам удалось определить убийцу! Открывайте конверт с признанием."
              - type: text
                text: "Вы успешно завершили расследование! Спасибо за игру!"
            transition: complete
          - id: wrong_killer
            when: otherwise
            actions:
              - type: text
                text: "Это не тот человек. Попробуйте еще раз."
            effects:
              - type: increment
                variable: wrong_scene3
                by: 1
            transition:
              goto: lora_scene3
```

Все четыре успешных выбора сцены 2 выражаются одной декларативной rule:

```text
{1,2}, {1,6}, {2,6}, {1,2,6}
```

Python special case не требуется.

## 19. Правила валидации

### ERROR — package нельзя публиковать/запускать

1. YAML синтаксически неверен, содержит повторяющийся mapping key или неизвестные обязательные shapes. Loader обязан обнаруживать duplicate YAML keys до преобразования в обычный словарь.
2. `schema_version` не поддерживается.
3. `game_id`/`version` не соответствуют пути package.
4. Дублируется пара `game_id + version`.
5. Нет manifest/game файла либо объявленного asset.
6. Asset path абсолютный, выходит за package root, имеет неверный тип или отсутствует.
7. `entry_scene` не существует.
8. Дублируется scene/interaction/outcome/variable/scheduled action ID.
9. `goto` указывает на неизвестную scene.
10. `choices.interaction` не существует в целевой/current scene или не имеет `choice`/совместимого input.
11. Неизвестны action, effect, transition, normalization или match strategy.
12. Predicate несовместим с InputSpec: например `selection` для text.
13. `otherwise` не последний или их несколько.
14. Не последний interaction содержит `otherwise` и тем самым безусловно затеняет последующие interactions.
15. Нет обработанного valid/default пути там, где interaction обязан быть total.
16. `min_items > max_items`, значения вне `allowed_values`, duplicate aliases/values.
17. Effect ссылается на неизвестную variable либо нарушает ее тип.
18. Schedule ссылается на неизвестный template или имеет отрицательную задержку.
19. Scheduled guard ссылается на неизвестную scene/status.
20. `complete` совмещен с `goto` либо terminal outcome оставляет противоречивые effects.
21. `version` не является корректной SemVer или не совпадает с каталогом version package.

### WARNING — запуск возможен, требуется review

1. Недостижимая scene.
2. Outcome затенен более ранней rule.
3. Потенциально пересекающиеся aliases/contains rules.
4. `contains` использует очень короткую строку.
5. Interaction не имеет `invalid` UX и полагается на fallback.
6. Scene с `stay`, которая никогда повторно не показывает prompt.
7. Variable объявлена, но не используется.
8. Asset объявлен, но не используется.
9. Scheduled action не имеет guard.
10. Scene не имеет пути к `complete` (допустимо для article hub, но заметно).
11. Choice labels/typed aliases конфликтуют.

Validator строит граф `goto`, проверяет ссылки и выполняет ограниченный статический анализ predicates. Он не пытается доказать все логические пересечения.

## 20. Формат game tests

Tests запускают pure engine с in-memory session и fake clock. Они не загружают adapter или PostgreSQL.

### Общая форма

```yaml
name: descriptive_name
game_id: killing_margo
game_version: 1.0.0
clock: "2026-01-01T12:00:00Z"
steps:
  - start: true
    expect:
      scene: margo_q3
      actions:
        - {type: text}

  - input:
      text: "Лео Миллер"
    expect:
      outcome: correct_leo
      scene: margo_q4
      actions:
        - {type: text, contains: "поразительны"}
      variables: {}
      status: in_progress
```

Допустимые assertions:

- exact/contains text только в tests;
- action types/order, media asset ID, choice interaction/options;
- scene, status и variables;
- outcome ID;
- scheduled action template, due time и idempotency key;
- отсутствие действий.

### Margo: partial и durable schedule

```yaml
name: margo_partial_then_articles
game_id: killing_margo
game_version: 1.0.0
initial:
  scene: margo_q4
steps:
  - input: {text: "11, 99"}
    expect:
      outcome: one_correct
      scene: margo_q4
      actions:
        - {type: text, contains: "Одно"}

  - set_scene: margo_q9
  - input: {text: "31 и 33"}
    expect:
      outcome: correct
      scene: margo_articles
      actions:
        - {type: text}
        - {type: media, asset: phone_recording}
      scheduled:
        - action: reveal_articles
          due_in_seconds: 300
          idempotency_key: reveal_articles
```

`set_scene` разрешен только test harness для коротких focused cases, не является game effect.

### Margo: semantic hint без platform callback

```yaml
name: margo_hint_yes_no
game_id: killing_margo
game_version: 1.0.0
initial:
  scene: margo_q3_hint
steps:
  - input:
      choice:
        interaction: hint_decision
        value: "yes"
    expect:
      outcome: yes
      scene: margo_q3
      actions:
        - {type: text, contains: "размер обуви"}
        - {type: text, contains: "Напиши имя"}

  - set_scene: margo_q3_hint
  - input:
      choice:
        interaction: hint_decision
        value: "no"
    expect:
      outcome: no
      scene: margo_q3
      actions:
        - {type: text, contains: "попробуй"}
        - {type: text, contains: "Напиши имя"}
```

Package test проверяет только semantic schedule request. Отдельный application/infrastructure integration test обязан сохранить действие, остановить/restart delivery pump, продвинуть fake/database clock до `due_at` и подтвердить единственную доставку после 300 секунд.

### Lora: все допустимые subsets сцены 2

```yaml
name: lora_scene2_allowed_subsets
game_id: lora_dein
game_version: 1.0.0
cases:
  - initial: {scene: lora_scene2, variables: {wrong_scene2: 0}}
    input: {text: "1,2"}
    expect: {outcome: valid_correct_subset, scene: lora_scene3}
  - initial: {scene: lora_scene2, variables: {wrong_scene2: 0}}
    input: {text: "1 6"}
    expect: {outcome: valid_correct_subset, scene: lora_scene3}
  - initial: {scene: lora_scene2, variables: {wrong_scene2: 0}}
    input: {text: "2 и 6"}
    expect: {outcome: valid_correct_subset, scene: lora_scene3}
  - initial: {scene: lora_scene2, variables: {wrong_scene2: 0}}
    input: {text: "1,2,6"}
    expect: {outcome: valid_correct_subset, scene: lora_scene3}
  - initial: {scene: lora_scene2, variables: {wrong_scene2: 0}}
    input: {text: "1,3"}
    expect:
      outcome: contains_wrong_suspect
      scene: lora_scene2
      variables: {wrong_scene2: 1}
```

Обязательные package test categories:

- happy path;
- invalid format;
- default wrong;
- partial/specific feedback;
- each transition and completion;
- each scheduled action/guard;
- choice yes/no;
- stale semantic choice на application test level;
- validator failures отдельно в общих unit tests.

## 21. Намеренно отложенные extension points

До появления подтвержденного требования не добавляются:

- regex matching;
- token/text unordered selection как новый parser;
- reusable scene templates/macros;
- localization catalogs;
- conditional `on_enter` и сложные boolean expressions;
- cancel/reschedule effects из game DSL;
- absolute scheduled timestamps и recurring schedules;
- weighted/random outcomes;
- parallel active scenes;
- nested games/chapters;
- arbitrary metadata для platform renderers;
- remote asset providers;
- migration scripts между game versions.

Расширение выполняется новой `schema_version` с backward-compatible loader либо явным converter, а не неформальным изменением смысла существующих полей.

## Проверка выразительности

1. Одна definition не содержит Telegram/VK objects.
2. Margo aliases, exact code/phrase, pairs, partial feedback и complete выражены rules.
3. Hint выражен generic choice scene без callback data.
4. Articles выражены двумя interactions; `"3"` читает статью, readiness меняет scene.
5. 300 секунд выражены durable schedule effect/template.
6. Lora scene 1 выражает specific combinations, counter и repeat.
7. Lora scene 2 выражает subset/min/max одной rule.
8. Lora scene 3 выражает exact single selection и complete.
9. Engine tests не требуют сети, API или БД.
10. Не введены механики, не нужные текущим играм/application lifecycle.
