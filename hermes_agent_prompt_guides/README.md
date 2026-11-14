# Hermes Agent · Prompting

Snapshots of the official Nous Research documentation from the `NousResearch/hermes-agent` repository, taken on 11 November 2026. The licence is included.

| Snapshot | Official source |
| --- | --- |
| [tips.md](snapshots/tips.md) | [Tips & Best Practices](https://hermes-agent.nousresearch.com/docs/guides/tips/) |
| [context-files.md](snapshots/context-files.md) | [Context Files](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files) |
| [use-soul-with-hermes.md](snapshots/use-soul-with-hermes.md) | [Use SOUL.md with Hermes](https://hermes-agent.nousresearch.com/docs/guides/use-soul-with-hermes) |
| [prompt-assembly.md](snapshots/prompt-assembly.md) | [Prompt Assembly](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/prompt-assembly.md) |

## For the Hermes variant in Prompta

- In a one-off request, state the goal, pass the needed input and describe the expected result.
- Take the target environment's tools into account. A repeatable process can be turned into a skill if the user wants that.
- Put project rules in the project context file. The general conversational style of a Hermes instance is set in `SOUL.md`.
- Use stages and completion criteria when the task calls for them. This is a Prompta decision; the guides studied have no mandatory format for a multi-step request.
