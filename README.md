Для реализации:
Участник	Комиссия	Когда платит	Прозрачность
Арендодатель	10%	После заезда арендатора (удерживается из выплаты)	Не платит за размещение, платит только за результат
Арендатор	5%	В момент бронирования (отдельной строкой)	Видит в чеке: "Сервисный сбор — 5%"
Платформа	15% суммарно	С каждой успешной сделки	Деньги приходят только за реальные бронирования

Также надо оплатить 50% остальную сумму при встрече ????????

Также надо добавить календарь занятости по часам и по дням(3 месяца)

Улучшить расчет пути бронировании (выгоднее взять на день и тд)

Улучшение Дизайн: (Белый + Синий + Зеленый)

Фильтр для арендодателя списка бронирований

Дизайн: (Белый + Синий + Зеленый)

По оплате нужен чек об оплате (хз)

## Запуск с SQLite3 (PowerShell)

### 1) Установить/обновить зависимости

```powershell
cd .\rental
& "..\.venv\Scripts\python.exe" -m pip install -r ".\requirements.txt"
```

### 2) Применить миграции

```powershell
& "..\.venv\Scripts\python.exe" manage.py migrate
```

### 3) Проверка

```powershell
& "..\.venv\Scripts\python.exe" manage.py check
& "..\.venv\Scripts\python.exe" manage.py runserver
```

## Запуск в Docker (SQLite3)

Из корня проекта:

```powershell
docker compose up --build
```

После старта приложение будет доступно по адресу:

```text
http://localhost:8000
```

Остановка:

```powershell
docker compose down
```

### Демонстрационный PostgreSQL (не используется приложением)

В `docker-compose.yml` добавлен отдельный сервис `postgres` в профиле `demo`.
Приложение по-прежнему работает на `SQLite3`.

Запуск только demo PostgreSQL:

```powershell
docker compose --profile demo up -d postgres
```

Запуск приложения + demo PostgreSQL:

```powershell
docker compose --profile demo up --build
```