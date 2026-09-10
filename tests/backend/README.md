# Адверсариальные тесты бэкенда

Каждый тест в этой папке **падает на текущем коде** и описывает один
подтверждённый дефект. Проходящий тест здесь означает, что дефект исправлен.

Ничего в `backend/**` не менялось: тесты работают через публичный HTTP-API и
сервисный слой. Отдельный модуль `settings_test.py` импортирует настройки
проекта целиком и поверх принудительно ставит SQLite в памяти — чтобы прогон не
зависел от Postgres из `docker-compose.yml`.

## Команда запуска

Из корня репозитория (`C:\Users\g00dhuman\Desktop\Уркия эже`), PowerShell:

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\venv\Scripts\python.exe -m django test tests.backend --settings=tests.backend.settings_test -v 2
```

Git Bash / sh:

```sh
cd "/c/Users/g00dhuman/Desktop/Уркия эже"
PYTHONIOENCODING=utf-8 \
PYTHONPATH="$PWD;$PWD/backend" \
./venv/Scripts/python.exe -m django test tests.backend --settings=tests.backend.settings_test -v 2
```

Один файл или один тест:

```sh
... -m django test tests.backend.test_auth_tokens --settings=tests.backend.settings_test
... -m django test tests.backend.test_domain_rules.OverdueAfterDeadlineExtension --settings=tests.backend.settings_test
```

## Ожидаемый результат на текущем коде

```
Ran 27 tests
FAILED (failures=27)
```

## Состав

| Файл | Что доказывает |
| --- | --- |
| `test_input_sanitization.py` | обход фильтра HTML управляющими символами; поля без `plain_text`; минимальная длина названия точки только при создании |
| `test_auth_tokens.py` | refresh-токен нельзя отозвать (ротация, смена пароля, админский сброс), срок скользит; 500 на refresh удалённого пользователя; `verify` для заблокированного |
| `test_domain_rules.py` | вторая просрочка не пишется в историю; хронология рейса против промежуточных точек; опоздание меньше минуты; плательщик по правилу не пересчитывается |
| `test_audit_and_reports.py` | вход и смена пароля не журналируются; удаление сотрудника обезличивает журнал и комментарии; отчёты не валидируют фильтры; логины видны рядовому сотруднику |
| `test_performance.py` | N+1 к справочнику курсов валют в списке рейсов и в поиске по номеру |
