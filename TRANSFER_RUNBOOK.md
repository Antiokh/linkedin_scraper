# LinkedIn Market Map Runbook

Этот runbook нужен для запуска сбора на другой машине.

## Что скопировать

- Весь репозиторий `linkedin_scraper`
- Файл сессии LinkedIn `linkedin_session.json`

Важно:
- `linkedin_session.json` содержит авторизационные данные Playwright
- не коммитить его в git
- если сессия протухнет, создать новую через `samples/browser_playground.py`

## Что уже есть в репозитории

- Базовый playground браузера:
  - `samples/browser_playground.py`
- Сбор market map:
  - `samples/collect_market_map.py`
- Обогащение лидеров по engagement:
  - `samples/enrich_leader_influence.py`
- Отдельная маркетинговая рамка:
  - `MARKETING_BRIEF.md`

## Установка

Рекомендуемая версия Python:

- `Python 3.13`

Проверка:

```powershell
py -3.13 --version
```

Установка пакета без venv:

```powershell
py -3.13 -m pip install --user -e .
py -3.13 -m playwright install chromium
```

## Проверка авторизации

```powershell
@'
import asyncio
from linkedin_scraper import BrowserManager, is_logged_in

async def main():
    async with BrowserManager(headless=True) as browser:
        await browser.load_session("linkedin_session.json")
        await browser.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        print("URL:", browser.page.url)
        print("TITLE:", await browser.page.title())
        print("LOGGED_IN:", await is_logged_in(browser.page))

asyncio.run(main())
'@ | py -3.13 -
```

Ожидаемо:

- `URL: https://www.linkedin.com/feed/`
- `LOGGED_IN: True`

## Если нужно создать новую сессию

```powershell
py -3.13 samples/browser_playground.py --url https://www.linkedin.com/login --wait-seconds 300 --save-session linkedin_session.json
```

## Основной запуск

### 1. Собрать базовый market map

```powershell
py -3.13 samples/collect_market_map.py --leaders-target 100 --builders-target 100 --leader-pages 4 --people-pages 3 --company-pages 3 --enrich-companies 0 --output-dir data/linkedin_market_map_core
```

Результаты:

- `data/linkedin_market_map_core/leaders.json`
- `data/linkedin_market_map_core/leaders.csv`
- `data/linkedin_market_map_core/builders.json`
- `data/linkedin_market_map_core/builders.csv`

### 2. Пересчитать лидеров по популярности и паттернам продвижения

```powershell
py -3.13 samples/enrich_leader_influence.py --leaders data/linkedin_market_map_core/leaders.json --pages-per-query 3 --output-dir data/linkedin_leader_influence
```

Результаты:

- `data/linkedin_leader_influence/leaders_ranked.json`
- `data/linkedin_leader_influence/leaders_top20.json`
- `data/linkedin_leader_influence/leader_posts_raw.json`

## Логика данных

### Leaders

`leaders.json`:

- тематический longlist людей по `#mvp`, `#bubble`, `#nocode`, `#startup`
- плюс people search fallback по запросам вроде `startup founder`, `bubble expert`

`leaders_ranked.json`:

- уже enriched-версия
- содержит:
  - `influence_score`
  - `post_mentions`
  - `avg_reactions`
  - `avg_comments`
  - `avg_reposts`
  - `promotion_styles`
  - `sample_posts`

### Builders

`builders.json`:

- люди и компании из people/company search
- фокус на:
  - `bubble`
  - `bubble.io`
  - `no-code`
  - `nocode`
  - `mvp`
  - `startup`

## Стартовый промпт для новой машины

Ниже готовый промпт для нового агента/чата.

```text
У нас локально открыт репозиторий linkedin_scraper.

Контекст задачи:
- Мы исследуем LinkedIn-рынок вокруг bubble / nocode / startup / mvp.
- Нужны 2 основных списка:
  1. leaders/influencers: самые заметные люди, чтобы понять, как они продвигаются
  2. builders: компании и разработчики, которые делают продукты на Bubble / no-code / MVP
- На этой машине уже должен быть файл linkedin_session.json с рабочей LinkedIn-сессией.

Что важно сделать в первую очередь:
1. Проверить, что linkedin_session.json рабочий и LinkedIn открывается.
2. Если нужно, установить зависимости:
   - py -3.13 -m pip install --user -e .
   - py -3.13 -m playwright install chromium
3. Собрать базовый market map:
   - py -3.13 samples/collect_market_map.py --leaders-target 100 --builders-target 100 --leader-pages 4 --people-pages 3 --company-pages 3 --enrich-companies 0 --output-dir data/linkedin_market_map_core
4. Затем обогатить лидеров по engagement:
   - py -3.13 samples/enrich_leader_influence.py --leaders data/linkedin_market_map_core/leaders.json --pages-per-query 3 --output-dir data/linkedin_leader_influence
5. После запуска:
   - прочитать results из data/linkedin_market_map_core и data/linkedin_leader_influence
   - коротко свести топ лидеров
   - выделить повторяющиеся promotion patterns: service_pitch, build_in_public, educational, case_study

Какие файлы смотреть:
- samples/collect_market_map.py
- samples/enrich_leader_influence.py
- data/linkedin_market_map_core/leaders.json
- data/linkedin_market_map_core/builders.json
- data/linkedin_leader_influence/leaders_ranked.json

Финальная цель:
- получить список наиболее популярных и релевантных LinkedIn-лидеров мнений
- понять, как именно они продвигаются
- получить структурированный список bubble/nocode builders и компаний
```

## Быстрый чек-лист

```powershell
py -3.13 -m pip install --user -e .
py -3.13 -m playwright install chromium
py -3.13 samples/collect_market_map.py --leaders-target 100 --builders-target 100 --leader-pages 4 --people-pages 3 --company-pages 3 --enrich-companies 0 --output-dir data/linkedin_market_map_core
py -3.13 samples/enrich_leader_influence.py --leaders data/linkedin_market_map_core/leaders.json --pages-per-query 3 --output-dir data/linkedin_leader_influence
```
