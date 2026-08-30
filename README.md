# Detective Bot

Новая codebase для platform-independent движка интерактивных игр-детективов.

Текущий этап реализует только:

- typed game package schema;
- pure game engine;
- YAML loader и semantic validator;
- filesystem game catalog;
- synthetic fixtures и unit tests.

Реальные `killing_margo` и `lora_dein` пока не мигрированы. Telegram/VK adapters, persistence и deployment также еще не реализованы.

## Требования

- Python 3.12
- Pydantic 2
- PyYAML 6
- pytest для разработки

## Установка для разработки

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Тесты

```bash
.venv/bin/python -m pytest
```

## Валидация game packages

Проверка каталога synthetic fixtures:

```bash
.venv/bin/python tools/validate_games.py tests/fixtures/games
```

Проверка отдельного package:

```bash
.venv/bin/python tools/validate_games.py \
  tests/fixtures/games/synthetic_detective/1.10.0
```

Валидатор возвращает ненулевой exit code при наличии `ERROR`; одни `WARNING` не считаются ошибкой команды.
