/** A digest of attached project files that do not fit the budget whole: a file tree, whole small files and
 *  outlines of long ones (headings, signatures, scripts, commands), extracted by code, not by a model, so it
 *  cannot invent anything. The most useful files come first and get the most room.
 *
 *  Input is already cleaned by context.ts (secrets redacted, block markers neutralized); the output goes inside
 *  the ATTACHED FILES block as `=== path ===` sections.
 */

export interface DigestFile {
  path: string;
  content: string;
}

/** How a file reached the model: its whole text, an outline (or its start), or only its line in the tree. */
export type FileUse = 'whole' | 'outline' | 'tree';

/** One line of an outline; level 0 is always kept, 1 and 2 are dropped first when the outline is too long. */
interface Item {
  text: string;
  level: 0 | 1 | 2;
}

/** Each file first gets this much (its outline without imports, or the whole file if it is short); the best files
 *  get more after. Small, so that a folder of a hundred files still shows most of them. */
export const BRIEF_CHARS = 600;
const TREE_CHARS = 3_000;
const LINE_CHARS = 240;

const ext = (path: string): string => {
  const name = baseName(path).toLowerCase();
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot + 1) : '';
};
const baseName = (path: string): string => path.slice(path.lastIndexOf('/') + 1);
const short = (line: string): string => (line.length <= LINE_CHARS ? line : `${line.slice(0, LINE_CHARS)}…`);
const lineCount = (text: string): number => (text ? text.replace(/\n$/, '').split('\n').length : 0);

const CODE_EXT = new Set('py ts tsx js jsx mjs cjs go rs java kt kts swift rb php c h cc cpp hpp cs scala sh bash zsh lua dart ex exs m mm'.split(' '));
const CONFIG_EXT = new Set('toml yaml yml ini cfg conf properties'.split(' '));

type Kind = 'markdown' | 'code' | 'json' | 'config' | 'make' | 'docker' | null;

function kindOf(path: string): Kind {
  const name = baseName(path);
  const e = ext(path);
  if (/^(Makefile|GNUmakefile|justfile)$/i.test(name) || e === 'mk') return 'make';
  if (/^(Dockerfile|Containerfile)/i.test(name)) return 'docker';
  if (/^\.env/i.test(name)) return 'config';
  if (['md', 'mdx', 'markdown'].includes(e)) return 'markdown';
  if (e === 'json') return 'json';
  if (CONFIG_EXT.has(e)) return 'config';
  if (CODE_EXT.has(e)) return 'code';
  return null;
}

// ---------- ranking ----------

const KEY_FILES = /^(readme|agents|claude|contributing|architecture)(\.(md|mdx|markdown|rst|txt))?$|^(package\.json|pyproject\.toml|setup\.py|setup\.cfg|cargo\.toml|go\.mod|gemfile|composer\.json|pom\.xml|build\.gradle(\.kts)?|requirements[\w.-]*\.txt|makefile|justfile|dockerfile|deno\.json)$/i;
const TEST_PATH = /(^|\/)(tests?|__tests__|spec|fixtures?|__snapshots__|snapshots?|testdata)\/|(\.|_)(test|spec)\.[a-z]+$|(^|\/)test_[^/]+$/i;
const GENERATED = /\.(min\.js|map|lock|snap)$|(^|\/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|cargo\.lock|uv\.lock|gemfile\.lock)$/i;

/** 0 is read first: README, manifests and agent rules near the root; then code, docs and build files; then data and
 *  other configs; tests and generated files last. A README deep in the tree describes a part, not the project. */
function tier(path: string): number {
  if (GENERATED.test(path)) return 4;
  if (TEST_PATH.test(path)) return 3;
  if (KEY_FILES.test(baseName(path)) && path.split('/').length <= 2) return 0;
  const kind = kindOf(path);
  if (kind === 'code' || kind === 'markdown' || kind === 'make' || kind === 'docker' || /(^|\/)\.github\/workflows\//.test(path)) return 1;
  return 2;
}

const STOP = new Set('the and for with that this from into your what when which write make create file files project code need want please add use using about like для как что это или его она они при так чтобы надо нужно сделай напиши файл файлы проект проекта код'.split(' '));

function requestWords(request: string): string[] {
  const words = request.toLowerCase().match(/[\p{L}\p{N}_-]{3,}/gu) ?? [];
  return [...new Set(words.filter((w) => !STOP.has(w)))].slice(0, 40);
}

/** Words of the request found in the path count three times, in the text once; each word counts once. */
function relevance(words: string[], file: DigestFile): number {
  const path = file.path.toLowerCase();
  const text = file.content.toLowerCase();
  return words.reduce((score, w) => score + (path.includes(w) ? 3 : text.includes(w) ? 1 : 0), 0);
}

/** File indexes, most useful first: by kind, then by the request's words, then shallower, then attach order.
 *  Key files go by depth before words: the root README describes the project whatever the request says. */
export function rankFiles(request: string, files: DigestFile[]): number[] {
  const words = requestWords(request);
  const keys = files.map((file, index) => ({
    index,
    tier: tier(file.path),
    score: relevance(words, file),
    depth: file.path.split('/').length,
  }));
  keys.sort((a, b) => a.tier - b.tier || (a.tier === 0 ? a.depth - b.depth : 0) || b.score - a.score || a.depth - b.depth || a.index - b.index);
  return keys.map((k) => k.index);
}

// ---------- outlines ----------

function markdownItems(content: string): Item[] {
  const items: Item[] = [];
  let fence: string | null = null;
  let fenceLines = 0;
  let firstBlock = true; // the first paragraph under a heading (or at the top) says what the section is about
  let firstChars = 0;
  for (const line of content.split('\n')) {
    const marker = line.match(/^\s*(```+|~~~+)/)?.[1];
    if (fence !== null) {
      if (marker && marker[0] === fence[0] && marker.length >= fence.length) {
        items.push({ text: line, level: 1 });
        fence = null;
      } else {
        fenceLines += 1;
        items.push({ text: short(line), level: fenceLines <= 8 ? 1 : 2 });
      }
      continue;
    }
    if (marker) {
      fence = marker;
      fenceLines = 0;
      items.push({ text: line, level: 1 });
      continue;
    }
    if (/^#{1,6}\s+\S/.test(line)) {
      items.push({ text: short(line), level: 0 });
      firstBlock = true;
      firstChars = 0;
      continue;
    }
    if (!line.trim()) {
      if (firstChars > 0) firstBlock = false;
      continue;
    }
    if (firstBlock && firstChars < 300) {
      firstChars += line.length;
      items.push({ text: short(line), level: 1 });
    } else {
      items.push({ text: short(line), level: 2 });
    }
  }
  return items;
}

const DECL = /^\s*(?:export\s+)?(?:default\s+)?(?:(?:public|private|protected|internal|static|abstract|final|async|override|open|sealed|data|inline|pub(?:\([^)]*\))?|unsafe|extern)\s+)*(?:def|class|function\*?|func|fn|interface|type|enum|struct|trait|impl|module|mod|object|record|protocol|extension|fun|const|let|var|val|namespace)\s+[\p{L}_$<]/u;
const METHOD = /^\s+(?:(?:public|private|protected|static|async|get|set|readonly|override)\s+)*[A-Za-z_$][\w$]*\s*(?:<[^>]*>)?\(.*\)\s*(?::\s*[^={;]+)?\s*\{\s*$/;
const CONTROL = /^\s*(?:if|for|while|switch|catch|return|else|do|try|with|elif|except|match|when)\b/;
const IMPORT = /^\s*(?:import\s|from\s+\S+\s+import\s|using\s|#include\s|use\s|require\s|(?:const|let|var)\s+.+=\s*require\()/;
const SHELL_FN = /^\s*(?:function\s+)?[\w-]+\s*\(\)\s*\{/;
const COMMENT = /^\s*(?:#|\/\/|\/\*|\*|"""|''')/;

function codeItems(content: string): Item[] {
  const lines = content.split('\n');
  const items: Item[] = [];
  let i = lines[0]?.startsWith('#!') ? 1 : 0;
  // The file's own header comment or module docstring: what the file is for.
  const header: string[] = [];
  let inDoc = false;
  for (; i < lines.length && header.length < 6; i += 1) {
    const line = lines[i] ?? '';
    if (!line.trim() && !inDoc) {
      if (header.length) break;
      continue;
    }
    if (inDoc || COMMENT.test(line)) {
      header.push(short(line));
      const quotes = (line.match(/"""|'''/g) ?? []).length;
      if (quotes % 2 === 1) inDoc = !inDoc;
      continue;
    }
    break;
  }
  items.push(...header.map((text) => ({ text, level: 1 as const })));
  // A module with exports: those are its interface, its own helpers and constants are detail.
  const exports = /^export\s/m.test(content);
  for (; i < lines.length; i += 1) {
    const line = lines[i] ?? '';
    if (!line.trim() || CONTROL.test(line)) continue;
    const top = !/^\s/.test(line);
    if (IMPORT.test(line)) {
      if (top) items.push({ text: short(line.trim()), level: 2 });
    } else if (DECL.test(line)) {
      const local = /^\s*(?:const|let|var|val)\s/.test(line);
      const inner = !top || (exports && !/^export\s/.test(line));
      if (top || !local) items.push({ text: short(line.trimEnd()), level: inner ? 1 : 0 });
    } else if (METHOD.test(line) || (top && SHELL_FN.test(line))) {
      items.push({ text: short(line.trimEnd()), level: top ? 0 : 1 });
    } else if (/^\s*@[\w.]+/.test(line) && DECL.test(lines[i + 1] ?? '')) {
      items.push({ text: short(line.trimEnd()), level: 2 }); // a decorator says what kind of function follows
    }
  }
  return items;
}

const jsonLine = (key: string, value: unknown): string => short(`${key}: ${JSON.stringify(value)}`);

function jsonItems(content: string): Item[] | null {
  let data: unknown;
  try {
    data = JSON.parse(content);
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  const items: Item[] = [];
  for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
    if (key === 'scripts' && value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [name, command] of Object.entries(value)) items.push({ text: jsonLine(`scripts.${name}`, command), level: 0 });
    } else if (/dependencies$/i.test(key) && value && typeof value === 'object' && !Array.isArray(value)) {
      items.push({ text: short(`${key}: ${Object.keys(value).join(', ')}`), level: /^dependencies$/.test(key) ? 1 : 2 });
    } else if (value !== null && typeof value === 'object') {
      const keys = Array.isArray(value) ? `[${value.length} items]` : `{${Object.keys(value).join(', ')}}`;
      items.push({ text: short(`${key}: ${keys}`), level: /^(bin|engines|exports|workspaces|compilerOptions)$/.test(key) ? 1 : 2 });
    } else {
      items.push({ text: jsonLine(key, value), level: /^(name|version|description|type|main|module|license)$/.test(key) ? 0 : 1 });
    }
  }
  return items;
}

function configItems(content: string): Item[] {
  const items: Item[] = [];
  for (const line of content.split('\n')) {
    if (!line.trim()) continue;
    const indent = line.length - line.trimStart().length;
    let level: 0 | 1 | 2;
    if (/^\s*[#;]/.test(line)) level = 2;
    else if (/^\s*\[/.test(line) || /^\s*-?\s*(run|script|command|commands)\s*:/.test(line)) level = 0;
    else level = indent === 0 ? 0 : indent <= 4 ? 1 : 2;
    items.push({ text: short(line.trimEnd()), level });
  }
  return items;
}

function makeItems(content: string): Item[] {
  return content.split('\n').filter((line) => line.trim()).map((line) => {
    if (/^\s*#/.test(line)) return { text: short(line), level: 2 as const };
    if (/^[^\s#=][^=]*?::?(?!=)(\s|$)/.test(line)) return { text: short(line), level: 0 as const };
    return { text: short(line), level: 1 as const };
  });
}

function dockerItems(content: string): Item[] {
  return content.split('\n').filter((line) => line.trim()).map((line) => {
    if (/^\s*#/.test(line) || /^\s/.test(line)) return { text: short(line), level: 2 as const };
    if (/^(FROM|CMD|ENTRYPOINT|EXPOSE|WORKDIR|ENV|ARG)\b/i.test(line)) return { text: short(line), level: 0 as const };
    return { text: short(line), level: 1 as const };
  });
}

function items(path: string, content: string): Item[] | null {
  switch (kindOf(path)) {
    case 'markdown': return markdownItems(content);
    case 'code': return codeItems(content);
    case 'json': return jsonItems(content);
    case 'config': return configItems(content);
    case 'make': return makeItems(content);
    case 'docker': return dockerItems(content);
    default: return null;
  }
}

/** The fullest outline that fits `cap`: every level that fits whole, then the next level's lines in document order
 *  while they fit (a long prose document keeps its opening text, not only its headings); cut if level 0 is too long. */
function render(list: Item[], cap: number): string {
  const text = (keep: (item: Item, index: number) => boolean) => list.filter(keep).map((item) => item.text).join('\n');
  for (const level of [2, 1, 0]) {
    const base = text((item) => item.level <= level);
    if (base.length > cap) continue;
    if (level === 2) return base;
    const keep = list.map((item) => item.level <= level);
    let size = base.length;
    for (const [index, item] of list.entries()) {
      if (item.level !== level + 1) continue;
      if (size + item.text.length + 1 > cap) break;
      keep[index] = true;
      size += item.text.length + 1;
    }
    return text((_, index) => keep[index]!);
  }
  // Whole lines only: half a signature misleads more than a missing one.
  const top = list.filter((item) => item.level === 0).map((item) => item.text);
  const kept: string[] = [];
  let size = 0;
  for (const line of top) {
    if (size + line.length + 1 > cap - 40) break;
    kept.push(line);
    size += line.length + 1;
  }
  return `${kept.join('\n')}\n[…${top.length - kept.length} more lines of outline…]`;
}

const startOf = (content: string, cap: number): string => `${content.slice(0, cap)}\n[…rest of the file omitted…]`;

interface Shown {
  header: string;
  body: string;
}

/** The file within `cap`: whole if it fits, else its outline, else (no outline for this kind) its start.
 *  `maxLevel` 1 leaves out imports and other detail even when they would fit. */
export function shrink(file: DigestFile, cap: number, maxLevel: 0 | 1 | 2 = 2): Shown & { use: FileUse } {
  if (file.content.length <= cap) return { header: `=== ${file.path} ===`, body: file.content, use: 'whole' };
  const lines = lineCount(file.content);
  const list = items(file.path, file.content)?.filter((item) => item.level <= maxLevel) ?? null;
  if (list && list.some((item) => item.level === 0 || item.level === 1)) {
    return { header: `=== ${file.path} (outline of ${lines} lines) ===`, body: render(list, cap), use: 'outline' };
  }
  return { header: `=== ${file.path} (start of ${lines} lines) ===`, body: startOf(file.content, cap), use: 'outline' };
}

const sectionLength = (shown: Shown): number => shown.header.length + 1 + shown.body.length + 2;

function tree(files: DigestFile[]): string {
  const lines = [...files]
    .sort((a, b) => a.path.localeCompare(b.path))
    .map((file) => `${file.path} · ${lineCount(file.content)} lines`);
  const kept: string[] = [];
  let size = 0;
  for (const line of lines) {
    if (size + line.length + 1 > TREE_CHARS) break;
    kept.push(line);
    size += line.length + 1;
  }
  const more = lines.length - kept.length;
  return `=== file tree (${files.length} files) ===\n${kept.join('\n')}${more ? `\n… and ${more} more` : ''}`;
}

/** The files within `budget`: the tree (two files or more), then every file it can afford, most useful first.
 *  Each file first gets BRIEF_CHARS; what is left lets the most useful files grow up to `perFile`. */
export function digestFiles(
  request: string,
  files: DigestFile[],
  budget: number,
  perFile: number,
): { text: string; uses: FileUse[] } {
  const uses: FileUse[] = files.map(() => 'tree');
  const parts: string[] = [];
  if (files.length > 1) parts.push(tree(files));
  let room = budget - (parts[0]?.length ?? 0) - 2;
  const order = rankFiles(request, files);
  const shown = new Map<number, Shown & { use: FileUse }>();
  // README, manifests and agent rules say the most per character: they get their full share before the rest,
  // up to half the room, so a hundred source outlines cannot crowd them out.
  let keyRoom = Math.floor(room / 2);
  for (const index of order) {
    if (tier(files[index]!.path) !== 0) continue;
    const rich = shrink(files[index]!, perFile);
    const cost = sectionLength(rich);
    if (cost <= keyRoom) {
      shown.set(index, rich);
      room -= cost;
      keyRoom -= cost;
    }
  }
  for (const index of order) {
    if (shown.has(index)) continue;
    const brief = shrink(files[index]!, Math.min(BRIEF_CHARS, perFile), 1);
    const cost = sectionLength(brief);
    if (cost <= room) {
      shown.set(index, brief);
      room -= cost;
    }
  }
  for (const index of order) {
    const brief = shown.get(index);
    if (!brief || brief.use === 'whole') continue;
    const rich = shrink(files[index]!, perFile);
    const extra = sectionLength(rich) - sectionLength(brief);
    if (extra > 0 && extra <= room) {
      shown.set(index, rich);
      room -= extra;
    }
  }
  for (const index of order) {
    const section = shown.get(index);
    if (!section) continue;
    uses[index] = section.use;
    parts.push(`${section.header}\n${section.body}`);
  }
  return { text: parts.join('\n\n'), uses };
}
