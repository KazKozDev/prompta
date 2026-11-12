# Hermes Agent · Prompting

Снимки официальной документации Nous Research из репозитория `NousResearch/hermes-agent`, полученные 11 ноября 2026 года. Лицензия приложена.

| Снимок | Официальный источник |
| --- | --- |
| [tips.md](snapshots/tips.md) | [Tips & Best Practices](https://hermes-agent.nousresearch.com/docs/guides/tips/) |
| [context-files.md](snapshots/context-files.md) | [Context Files](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files) |
| [use-soul-with-hermes.md](snapshots/use-soul-with-hermes.md) | [Use SOUL.md with Hermes](https://hermes-agent.nousresearch.com/docs/guides/use-soul-with-hermes) |
| [prompt-assembly.md](snapshots/prompt-assembly.md) | [Prompt Assembly](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/prompt-assembly.md) |

## Для варианта Hermes в Prompta

- В разовом запросе сформулировать цель, передать нужные входные данные и обозначить ожидаемый результат.
- Учитывать инструменты целевой среды. Повторяемый процесс можно оформить как skill, если пользователь этого хочет.
- Правила проекта помещать в проектный файл контекста. Общий стиль общения экземпляра Hermes задаётся в `SOUL.md`.
- Использовать этапы и критерии готовности, когда этого требует задача. Это решение для Prompta, обязательного формата многошагового запроса в изученных руководствах нет.
