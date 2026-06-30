# agent-browser / агент-браузер

## English

`agent-browser` is a Codex/agent skill for safe browser automation in a per-user sandbox. It exposes one skill-owned browser tool instead of asking agents to run raw browser commands. The skill focuses on deterministic, artifact-backed workflows: page Markdown inspection, typed node actions, protected artifact reads, manual desktop/noVNC handoff, persistent profiles, downloads, and Saby/SBIS tender CSV export.

### What is in this repository

- `skill.json` — skill manifest, tool schema, action list, prompts, protected paths, and current version.
- `SKILL.md` and `AUTOLOAD.md` — operating prompts for agents.
- `scripts/browser_tool.py` — executable tool wrapper.
- `scripts/agent_browser_skill/` — Python runtime, action dispatch, browser helpers, artifact handling, extractors, domain helpers, and diagnostics.
- `reference/` — detailed user and maintainer documentation.
- `examples/` — practical workflow examples.
- `tests/` — regression tests, fixtures, and golden outputs.

### Development workflow

1. Read `AGENTS.md` before editing.
2. Keep changes minimal and backward compatible unless a breaking change is explicitly required.
3. For every repository change, keep these files synchronized:
   - `skill.json` `version`
   - `scripts/agent_browser_skill/version.py` `SKILL_VERSION`
   - the newest section in `CHANGELOG.md`
4. Prefer typed browser actions and fixture-based tests over live network or raw browser scraping.
5. Do not commit generated caches, browser profiles, protected artifacts, secrets, or local diagnostics.

### Recommended checks

```bash
python -m pytest tests
python -m json.tool skill.json >/dev/null
```

Run narrower targeted checks when appropriate, and document any environment limitation in the final report.

## Русский

`agent-browser` — это skill для Codex/агентов, который безопасно автоматизирует браузер в пользовательской sandbox-среде. Вместо прямого запуска сырых браузерных команд агент использует один управляемый инструмент. Основной подход: детерминированные сценарии с артефактами — Markdown-представление страницы, типизированные действия по `node_id`, защищённое чтение артефактов, ручная сессия desktop/noVNC, постоянные профили, загрузки файлов и экспорт тендеров Saby/SBIS в CSV.

### Что находится в репозитории

- `skill.json` — манифест skill: схема инструмента, список action, prompt-файлы, защищённые пути и версия.
- `SKILL.md` и `AUTOLOAD.md` — инструкции для агентов.
- `scripts/browser_tool.py` — исполняемая обёртка инструмента.
- `scripts/agent_browser_skill/` — Python runtime, диспетчер действий, браузерные helper-модули, артефакты, extractors, доменные helper-модули и диагностика.
- `reference/` — подробная документация для пользователей и сопровождающих.
- `examples/` — практические примеры сценариев.
- `tests/` — регрессионные тесты, fixtures и golden outputs.

### Рабочий процесс разработки

1. Перед изменениями прочитайте `AGENTS.md`.
2. Делайте минимальные изменения и сохраняйте обратную совместимость, если явно не требуется breaking change.
3. При любом изменении синхронизируйте:
   - `version` в `skill.json`
   - `SKILL_VERSION` в `scripts/agent_browser_skill/version.py`
   - верхний раздел `CHANGELOG.md`
4. Предпочитайте типизированные browser actions и тесты на fixtures вместо live network или сырого browser scraping.
5. Не коммитьте generated caches, browser profiles, protected artifacts, secrets и локальную диагностику.

### Рекомендуемые проверки

```bash
python -m pytest tests
python -m json.tool skill.json >/dev/null
```

Если нужна более узкая проверка — запускайте её, а ограничения окружения фиксируйте в итоговом отчёте.
