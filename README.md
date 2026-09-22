# Threads-автопилот - «Контент-машина на AI» (прогрев)

Автономная публикация коротких историй с хуками от первого лица в Threads.
Цель этапа: раскачать аудиторию и собрать подписчиков. Без ссылок на продукт.

## Как это устроено

- `content_bank.json` - банк готовых постов (id, тема, текст). Сейчас 30 штук: темы `content_ai`, `growth`, `ai_wow`.
- `threads_client.py` - постинг через официальный Threads Graph API (чистый HTTP, только stdlib).
- `state.json` - что уже опубликовано (создаётся автоматически, идемпотентность).
- `secrets.json` - токен (создать из `secrets.example.json`, НЕ коммитить).
- `post_slot.cmd` - обёртка для Windows-планировщика.
- `post.log` / `post_slots.log` - логи.

Постинг = чистый HTTP, **Claude/приложение не требуется**. Работает само по расписанию.

---

## ШАГ 1. Получить токен Threads API (делается один раз, ~20-30 мин, нужен твой логин)

Я не могу залогиниться за тебя, поэтому этот шаг делаешь ты. Я рядом на каждом пункте.

1. Зайти на **developers.facebook.com** под своим аккаунтом (тем, к которому привязан нужный Threads-профиль).
2. **My Apps → Create App**. Тип: выбрать сценарий с доступом к **Threads API** (Use case: "Access the Threads API").
3. В приложении открыть продукт **Threads → Settings**:
   - в **Threads API permissions** включить `threads_basic` и `threads_content_publish`;
   - добавить redirect URI (можно временный, напр. `https://localhost/`), он нужен формально.
4. Добавить свой Threads-аккаунт как тестировщика: **Roles → Threads testers → Add**, затем зайти в приложении Threads (телефон): Настройки → Аккаунт → Website permissions / Invites → принять инвайт.
5. Сгенерировать **короткоживущий токен** для своего пользователя (кнопка "Generate access token" в разделе Threads → Use cases, с галками `threads_basic` + `threads_content_publish`). Скопировать его.
6. В **App settings → Basic** скопировать **App secret** (App ID тоже пригодится).

## ШАГ 2. Заполнить secrets.json

```bash
copy secrets.example.json secrets.json
```

Вписать в `secrets.json`:
- `access_token` - короткоживущий токен из шага 1.5;
- `app_secret` - из шага 1.6;
- `user_id` - оставить пустым (подтянется сам).

## ШАГ 3. Обменять на долгоживущий токен (60 дней) и проверить

```bash
"C:\Users\asus\AppData\Local\Python\bin\python.exe" threads_client.py token-exchange
"C:\Users\asus\AppData\Local\Python\bin\python.exe" threads_client.py me
```

`me` должен вывести твой id и @username - значит токен рабочий.

## ШАГ 4. Тестовый пост

```bash
"C:\Users\asus\AppData\Local\Python\bin\python.exe" threads_client.py post-next
```

Проверь, что пост появился в Threads. Дальше он больше не повторится (запомнен в state.json).

---

## ШАГ 5. Расписание (2-3 поста в день, prime-time)

Три обычные Windows-задачи (Task Scheduler, Run as текущий пользователь), каждая запускает `post_slot.cmd`.
Пример времени МСК: **10:30, 14:30, 19:30**. `post-next` идемпотентен + защита от двойного запуска (min-interval 90 мин).

Быстрое создание из PowerShell (правь время под себя):

```powershell
$cmd = "C:\Claude\content-machine-threads\post_slot.cmd"
schtasks /Create /TN "Threads Post 1" /TR $cmd /SC DAILY /ST 10:30 /F
schtasks /Create /TN "Threads Post 2" /TR $cmd /SC DAILY /ST 14:30 /F
schtasks /Create /TN "Threads Post 3" /TR $cmd /SC DAILY /ST 19:30 /F
```

30 постов в банке = ~10-15 дней автопилота при 2-3 постах в день.

## Поддержка токена

Долгоживущий токен живёт 60 дней. Обновлять заранее (можно раз в ~50 дней):

```bash
"C:\Users\asus\AppData\Local\Python\bin\python.exe" threads_client.py token-refresh
```

## Пополнение банка

- Быстро добавить один пост: `python threads_client.py add "текст поста"`
- Пачкой: попросить Claude сгенерировать новые истории и дописать в `content_bank.json` (см. `playbook.md`).

## Лимиты Threads API

- До 250 постов за 24 часа на аккаунт - с запасом.
- Текст до 500 символов на пост (в банке все укладываются).
