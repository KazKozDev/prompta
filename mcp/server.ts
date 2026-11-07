/** Prompta as an MCP server (stdio, newline-delimited JSON-RPC 2.0). No SDK, same as the rest of the pipeline.
 *
 *  Agents call it with their current conversation as context:
 *  - improve_prompt: rough request + context → ready prompt built by the Prompta pipeline;
 *  - suggest_next_prompts: context → a few ready next messages grounded in where the work stands.
 *
 *  LLM settings come from the environment (or .env.local in the repo root):
 *  PROMPTA_PROVIDER=ollama|openai|gemini, PROMPTA_MODEL, PROMPTA_API_KEY, PROMPTA_BASE_URL.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { loadCatalog } from '../pipeline/catalog.ts';
import { composeThoughts } from '../pipeline/context.ts';
import { runPipeline } from '../pipeline/index.ts';
import { createLLM } from '../pipeline/llm.ts';
import type { Provider } from '../pipeline/llm.ts';
import { suggestNextPrompts } from '../pipeline/suggest.ts';
import type { Catalog, LLM, PipelineResult } from '../pipeline/types.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const SERVER_INFO = { name: 'prompta', version: '0.1.0' };
const PROTOCOL_VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05'];
const TARGETS = ['auto', 'claude', 'chatgpt', 'gemini', 'grok'] as const;
type Target = (typeof TARGETS)[number];

type Json = Record<string, unknown>;
interface RpcMessage { jsonrpc?: string; id?: string | number | null; method?: unknown; params?: unknown }
export type Send = (message: Json) => void;

const TOOLS = [
  {
    name: 'improve_prompt',
    title: 'Improve a prompt with Prompta',
    description:
      'Turn the user\'s rough request into a well-structured, ready-to-send prompt using Prompta (official provider prompting rules or a prompting-technique catalog). '
      + 'Pass the recent conversation as `context` so the prompt fits the current situation. Show the returned prompt to the user; do not execute it unless they ask.',
    inputSchema: {
      type: 'object',
      properties: {
        request: { type: 'string', description: 'What the user wants, in their own words (draft prompt or wish).' },
        context: { type: 'string', description: 'Relevant recent conversation: user messages, what was done, files, errors. Plain text.' },
        target: { type: 'string', enum: [...TARGETS], description: 'Model the prompt is for. auto = generic technique catalog.' },
        variants: { type: 'integer', minimum: 1, maximum: 3, description: 'How many alternative prompts to return (default 1).' },
      },
      required: ['request'],
    },
    annotations: { readOnlyHint: true, openWorldHint: true },
  },
  {
    name: 'suggest_next_prompts',
    title: 'Suggest next prompts',
    description:
      'Given the conversation so far, propose the most useful next messages the user could send (fix what failed, verify unverified work, clarify, next step). '
      + 'Pass a faithful transcript or summary as `context`, including errors and open questions. Present the suggestions to the user to choose from.',
    inputSchema: {
      type: 'object',
      properties: {
        context: { type: 'string', description: 'The conversation so far (transcript or faithful summary).' },
        goal: { type: 'string', description: 'Optional: what the user ultimately wants.' },
        target: { type: 'string', description: 'Optional: who receives the message, e.g. "Claude Code".' },
        language: { type: 'string', description: 'Language the user writes in, e.g. "ru" or "en". Pass it whenever known.' },
        count: { type: 'integer', minimum: 1, maximum: 5, description: 'Number of suggestions (default 3).' },
      },
      required: ['context'],
    },
    annotations: { readOnlyHint: true, openWorldHint: true },
  },
];

class ToolInputError extends Error {}

function str(args: Json, key: string, required = false): string | undefined {
  const v = args[key];
  if (v === undefined || v === null) {
    if (required) throw new ToolInputError(`"${key}" is required.`);
    return undefined;
  }
  if (typeof v !== 'string') throw new ToolInputError(`"${key}" must be a string.`);
  if (required && !v.trim()) throw new ToolInputError(`"${key}" must not be empty.`);
  return v;
}

function int(args: Json, key: string, min: number, max: number, fallback: number): number {
  const v = args[key];
  if (v === undefined || v === null) return fallback;
  if (typeof v !== 'number' || !Number.isInteger(v) || v < min || v > max) throw new ToolInputError(`"${key}" must be an integer from ${min} to ${max}.`);
  return v;
}

function formatImprove(result: PipelineResult): { text: string; structured: Json } {
  const prompts = [
    { name: result.choice.name, prompt: result.synthesis.prompt },
    ...(result.alternatives ?? []).map((a, i) => ({ name: `${a.choice.name} · variant ${i + 2}`, prompt: a.synthesis.prompt })),
  ];
  const warnings = [...new Set([result.synthesis, ...(result.alternatives ?? []).map((a) => a.synthesis)].flatMap((s) => s.warnings))];
  const missing = result.synthesis.missing;
  const parts = prompts.map((p, i) => `${prompts.length > 1 ? `## Variant ${i + 1}: ` : '## '}${p.name}\n\n${p.prompt}`);
  if (missing.length) parts.push(`Missing information: ${missing.join(', ')}`);
  if (warnings.length) parts.push(`Notes: ${warnings.join(' ')}`);
  return {
    text: `Topic: ${result.brief.topic ?? result.brief.goal}\n\n${parts.join('\n\n')}`,
    structured: { topic: result.brief.topic ?? result.brief.goal, technique: result.choice.key, prompts, missing, warnings },
  };
}

export interface ServerDeps {
  /** Created lazily so tools/list works even before an LLM is configured. */
  getLLM: () => Promise<LLM>;
  getCatalog: () => Catalog;
}

export function createServer(deps: ServerDeps) {
  async function callTool(name: string, args: Json, progress: (p: number, msg: string) => void): Promise<Json> {
    if (name === 'improve_prompt') {
      const request = str(args, 'request', true)!;
      const target = (str(args, 'target') ?? 'auto') as Target;
      if (!TARGETS.includes(target)) throw new ToolInputError(`"target" must be one of: ${TARGETS.join(', ')}.`);
      const variants = int(args, 'variants', 1, 3, 1);
      const llm = await deps.getLLM();
      const result = await runPipeline({
        thoughts: composeThoughts(request, str(args, 'context')),
        catalog: target === 'auto' ? deps.getCatalog() : { version: 'official-only', techniques: [] },
        llm,
        variants,
        claudeOnly: target === 'claude',
        chatgptOnly: target === 'chatgpt',
        geminiOnly: target === 'gemini',
        grokOnly: target === 'grok',
        onProgress: progress,
      });
      const { text, structured } = formatImprove(result);
      return { content: [{ type: 'text', text }], structuredContent: structured };
    }
    if (name === 'suggest_next_prompts') {
      const context = str(args, 'context', true)!;
      const count = int(args, 'count', 1, 5, 3);
      const llm = await deps.getLLM();
      progress(10, 'Reading the conversation');
      const suggestions = await suggestNextPrompts({ context, goal: str(args, 'goal'), target: str(args, 'target'), language: str(args, 'language'), count, llm });
      const text = suggestions.map((s, i) => `## ${i + 1}. ${s.title}\nWhy: ${s.why}\n\n${s.prompt}`).join('\n\n');
      return { content: [{ type: 'text', text }], structuredContent: { suggestions } };
    }
    throw new RpcError(-32602, `Unknown tool: ${name}`);
  }

  /** Handles one incoming message; replies go through `send` (also used for progress notifications). */
  async function handle(msg: RpcMessage, send: Send): Promise<void> {
    const isRequest = msg.id !== undefined && msg.id !== null;
    const reply = (body: Json) => isRequest && send({ jsonrpc: '2.0', id: msg.id, ...body });
    if (typeof msg !== 'object' || msg === null || typeof msg.method !== 'string') {
      reply({ error: { code: -32600, message: 'Invalid request' } });
      return;
    }
    const params = (msg.params && typeof msg.params === 'object' ? msg.params : {}) as Json;
    try {
      switch (msg.method) {
        case 'initialize': {
          const asked = typeof params.protocolVersion === 'string' ? params.protocolVersion : '';
          reply({ result: {
            protocolVersion: PROTOCOL_VERSIONS.includes(asked) ? asked : PROTOCOL_VERSIONS[0],
            capabilities: { tools: { listChanged: false } },
            serverInfo: SERVER_INFO,
            instructions: 'Prompta writes prompts. Use suggest_next_prompts when the user asks what to do or say next; use improve_prompt to turn a rough request into a strong prompt. Always pass the relevant conversation as context.',
          } });
          return;
        }
        case 'ping':
          reply({ result: {} });
          return;
        case 'tools/list':
          reply({ result: { tools: TOOLS } });
          return;
        case 'tools/call': {
          const name = params.name;
          if (typeof name !== 'string') throw new RpcError(-32602, 'Tool name is required.');
          const args = (params.arguments && typeof params.arguments === 'object' ? params.arguments : {}) as Json;
          const token = (params._meta as Json | undefined)?.progressToken;
          const progress = (p: number, message: string) => {
            if (token !== undefined) send({ jsonrpc: '2.0', method: 'notifications/progress', params: { progressToken: token, progress: p, total: 100, message } });
          };
          try {
            reply({ result: await callTool(name, args, progress) });
          } catch (error) {
            if (error instanceof RpcError) throw error;
            // Tool failures are results, so the agent can read and report them.
            reply({ result: { isError: true, content: [{ type: 'text', text: `Prompta error: ${error instanceof Error ? error.message : String(error)}` }] } });
          }
          return;
        }
        default:
          if (msg.method.startsWith('notifications/')) return;
          throw new RpcError(-32601, `Method not found: ${msg.method}`);
      }
    } catch (error) {
      const code = error instanceof RpcError ? error.code : -32603;
      reply({ error: { code, message: error instanceof Error ? error.message : String(error) } });
    }
  }

  return { handle };
}

class RpcError extends Error {
  readonly code: number;
  constructor(code: number, message: string) {
    super(message);
    this.code = code;
  }
}

function readEnvLocal(): Record<string, string> {
  const path = join(root, '.env.local');
  if (!existsSync(path)) return {};
  return Object.fromEntries(
    readFileSync(path, 'utf8').split('\n').map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#') && l.includes('='))
      .map((l) => { const i = l.indexOf('='); return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^["']|["']$/g, '')]; }),
  );
}

/** Builds the LLM from the environment; with Ollama and no model set, picks the first local model. */
export async function llmFromEnv(env: Record<string, string | undefined>, fetchImpl: typeof fetch = fetch): Promise<LLM> {
  const provider = (env.PROMPTA_PROVIDER || 'ollama') as Provider;
  if (!['ollama', 'openai', 'gemini'].includes(provider)) throw new Error(`PROMPTA_PROVIDER must be ollama, openai or gemini (got "${provider}").`);
  const baseUrl = env.PROMPTA_BASE_URL || undefined;
  const apiKey = env.PROMPTA_API_KEY || (provider === 'gemini' ? env.GEMINI_API_KEY : provider === 'openai' ? env.OPENAI_API_KEY : undefined);
  let model = env.PROMPTA_MODEL || '';
  if (!model && provider === 'ollama') {
    try {
      const res = await fetchImpl(`${baseUrl ?? 'http://localhost:11434'}/api/tags`);
      const data = (await res.json()) as { models?: { name?: string; remote_host?: string }[] };
      // Never auto-pick a cloud-proxied model (it would ship conversations off the machine) or an embedding model.
      model = data.models?.find((m) => typeof m.name === 'string' && !m.remote_host
        && !/[:-]cloud\b/i.test(m.name) && !/embed|bge-|rerank/i.test(m.name))?.name ?? '';
    } catch { /* reported below */ }
    if (!model) throw new Error('No local Ollama chat model found. Start Ollama and pull a model, or set PROMPTA_MODEL.');
  }
  if (!model) throw new Error('Set PROMPTA_MODEL for the Prompta MCP server.');
  if (provider !== 'ollama' && !apiKey) throw new Error(`Set PROMPTA_API_KEY for provider ${provider}.`);
  return createLLM({ provider, model, apiKey, baseUrl });
}

function main() {
  // stdout carries protocol messages only; any stray log would corrupt the stream.
  console.log = console.info = console.debug = (...args: unknown[]) => console.error(...args);
  const env = { ...readEnvLocal(), ...process.env };
  let llm: Promise<LLM> | undefined;
  let catalog: Catalog | undefined;
  const server = createServer({
    getLLM: () => {
      llm ??= llmFromEnv(env).catch((e) => { llm = undefined; throw e; });
      return llm;
    },
    getCatalog: () => (catalog ??= loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')))),
  });
  const send: Send = (message) => { process.stdout.write(`${JSON.stringify(message)}\n`); };

  let buffer = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk: string) => {
    buffer += chunk;
    let newline: number;
    while ((newline = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      let msg: RpcMessage;
      try {
        msg = JSON.parse(line) as RpcMessage;
      } catch {
        send({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } });
        continue;
      }
      // Requests run concurrently: a slow generation must not block ping or tools/list.
      void server.handle(msg, send);
    }
  });
  process.stdin.on('end', () => process.exit(0));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
