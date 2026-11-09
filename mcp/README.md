# Prompta MCP server

Lets any MCP-capable agent or chat client (Claude Code, Cursor, Cline, Claude Desktop, Codex…) call Prompta with the current conversation as context.

| Tool | Input | Returns |
|---|---|---|
| `suggest_next_prompts` | `context` (conversation), optional `goal`, `target`, `language`, `count` (1–5, default 3) | Ready-to-send next messages, each with a short title and why it fits the current state |
| `improve_prompt` | `request` (rough wish or draft), optional `context`, `target` (`auto` · `claude` · `chatgpt` · `gemini` · `grok`), `variants` (1–3) | A structured prompt built by the Prompta pipeline: official provider rules for a named target, the technique catalog for `auto` |

The server speaks MCP over stdio and has no dependencies beyond Node (it runs `.ts` directly, as the rest of the repo does).

## Model configuration

Set these in the client's MCP config (or in `.env.local` at the repo root):

| Variable | Default | Notes |
|---|---|---|
| `PROMPTA_PROVIDER` | `ollama` | `ollama`, `openai` (any OpenAI-compatible API), `gemini`, `anthropic` or `xai` |
| `PROMPTA_MODEL` | first **local** Ollama chat model | Set it explicitly: the automatic choice skips `:cloud` and embedding models but is otherwise arbitrary |
| `PROMPTA_API_KEY` | `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `XAI_API_KEY` | Required for every provider except `ollama` |
| `PROMPTA_BASE_URL` | provider default | e.g. LM Studio `http://localhost:1234` with `openai` |

Context sent by the agent is trimmed to its newest ~12k characters, and common secrets (API keys, tokens, private keys, `password=` values) are redacted before it reaches the model. The context is treated as data: `<<<`/`>>>` markers inside it are neutralized so it cannot close its block and add a task of its own.

## Connect

Claude Code:

```bash
claude mcp add prompta -e PROMPTA_MODEL=qwen3:8b -- node /absolute/path/to/prompta/mcp/server.ts
```

Generations take tens of seconds on a local model; if the client times out, raise its tool timeout (for Claude Code: `MCP_TOOL_TIMEOUT=300000`).

Cursor (`~/.cursor/mcp.json`), Claude Desktop (`claude_desktop_config.json`) and most other clients:

```json
{
  "mcpServers": {
    "prompta": {
      "command": "node",
      "args": ["/absolute/path/to/prompta/mcp/server.ts"],
      "env": { "PROMPTA_MODEL": "qwen3:8b" }
    }
  }
}
```

Then ask the agent things like "what should I ask next? use prompta" or "improve this prompt with prompta for Claude".

## Development

```bash
npm test          # includes mcp/server.test.ts (protocol, tools, redaction, real stdio handshake)
npm run mcp       # start the server on stdio
```
