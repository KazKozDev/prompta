"""Build catalog/source-excerpts.ts: for every technique, the passage of its downloaded source
(archive-org-prompting/md, by the pages in source_ref) and its original arXiv paper (source-links.json).

The synthesis prompts quote these passages, so every generated prompt is grounded in the sources
themselves, not only in the catalog's summary of them.  Run: python3 catalog/build_excerpts.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "archive-org-prompting" / "md"
LIMIT = 1400  # characters per passage; enough for the method, cheap enough for every call
PAGE = re.compile(r"<!-- page (\d+) -->")
ABBREV = {  # source_ref prefix -> document slug
    "whitepaper": "google-prompt-engineering-whitepaper-v7", "review": "review-prompt-techniques-cot-tot-got",
    "heston": "heston-prompt-engineering-medicine-2023", "med-ed": "prompt-engineering-in-medical-education",
    "hunter": "nathan-hunter-art-of-prompt-engineering", "shah": "antor-shah-prompt-engineering",
    "handbook": "practical-beginners-handbook-ai", "§": "the-prompt-report-arxiv-2406.06608",
}


EXTRA = {  # how the Prompt Report itself names techniques whose catalog name differs
    "icl_knn_selection": ["K-Nearest Neighbor", "KNN"], "icl_exemplar_settings": ["Exemplar Quantity", "Exemplar Ordering"],
    "meta_reasoning_cots": ["Meta-Reasoning over Multiple CoTs", "MCR"], "regex_extractor": ["Regex"],
    "injection_defenses": ["Prompt-based Defenses", "Guardrails", "Detectors"],
    "graph_of_thought": ["Graph-of-Thought (GoT) Prompting", "GoT represents the most advanced approach"],
    "dspy": ["the DSPy framework"],  # page 42 opens with a chart labelled "DSPy Default"; the method is the case-study paragraph
}

# Where the PDF's two columns interleave around the cited passage, the extracted summary reads as nonsense:
# a short description written from the passage replaces it (key, source reference) → text.
WRITTEN_SUMMARIES = {
    ("dspy", "§6.2.3, p. 42"): (
        "Case study: after a manual prompt-engineering process, the authors tried DSPy, which automatically "
        "optimizes LLM prompts for a target metric. Over 16 iterations it bootstrapped LLM-generated "
        "demonstrations and sampled training exemplars. The authors conclude that automated prompt search is "
        "promising, but combining it with human prompt engineering worked best."),
}


def pages_of(text: str) -> dict[int, str]:
    parts = PAGE.split(text)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def title_of(text: str) -> str:
    match = re.search(r'^title:\s*"?(.*?)"?\s*$', text, re.M)
    return match.group(1) if match else ""


def aliases(name: str, key: str) -> list[str]:
    found = [part.strip() for part in re.split(r"[()]", name) if len(part.strip()) > 2]
    found.sort(key=len, reverse=True)
    found = EXTRA.get(key, []) + found
    found.append(key.replace("_", " "))
    found += [a.replace("-", " ") for a in found] + [a.replace(" ", "-") for a in found]
    extra = EXTRA.get(key, [])
    rest = sorted(dict.fromkeys(a for a in found if a and a not in extra), key=len, reverse=True)
    return extra + rest  # explicit headings first, then the longest name: "Graph-of-Thought" before "GoT"


def clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def passage(doc_pages: dict[int, str], start: int, end: int, names: list[str]) -> str:
    chunk = "\n".join(doc_pages.get(p, "") for p in range(start, min(end, start + 3) + 1))
    whole = "\n".join(doc_pages[p] for p in sorted(doc_pages))
    for name in names:  # full name anywhere beats an abbreviation on the cited page: "Graph of Thought" before "GoT"
        for haystack in (chunk, whole):
            lower = haystack.lower()
            for hit in (m.start() for m in re.finditer(re.escape(name.lower()), lower)):
                paragraph = haystack.rfind("\n\n", 0, hit)
                at = paragraph + 2 if 0 <= hit - paragraph < 300 else max(0, hit - 80)
                window = haystack[at:at + LIMIT]
                head = window[:240]
                if ("@misc{" in window or window.count("%") >= 3 or "http" in head
                        or re.search(r"\[\d+\]\s*[\"“]", head)):  # bibliography, links or statistics, not the method
                    continue
                return clean(window)
    return ""  # better no passage than an unrelated one


ABBR = ("et al.", "e.g.", "i.e.", "vs.", "Fig.", "Eq.", "approx.", "cf.")


def readable(text: str) -> str:
    """PDF text as prose: drop heading lines and footnote markers, join wrapped lines."""
    lines = [l.strip() for l in text.splitlines()]
    # Headings ("Zero-Shot Prompting", "Chapter 4: ...") and figure labels ("4.1.") are short lines without
    # closing punctuation; wrapped PDF column lines are longer.
    lines = [l for l in lines if l and not re.fullmatch(r"[\d.\s]+", l)
             and not (len(l.split()) <= 5 and not l.endswith((".", ",", ";", ":", "!", "?", '"', "”", ")")))]
    prose = " ".join(lines)
    prose = re.sub(r"(\w)- (\w)", r"\1\2", prose)            # hyphenation across lines
    prose = re.sub(r"(?<=[a-z\)])\s?\d{1,2}(?=\s[a-z])", "", prose)  # "(CoT) 9 prompting"
    prose = re.sub(r"\.(\d{1,2})(?=\s)", ".", prose)         # "(ToT).12 It"
    prose = re.sub(r"\s*\[\d+(?:,\s*\d+)*\]", "", prose)       # "[3], [4]" citations
    return re.sub(r"\s+", " ", prose).strip()


METHOD = re.compile(r"\b(we (?:introduce|propose|present|show|find|explore|develop|study|describe)|here we|this (?:paper|work)|in this (?:paper|work))\b", re.I)


def summary(text: str, count: int = 4, limit: int = 640, focus: list[str] | None = None) -> str:
    """3-4 whole sentences within limit. Abstracts start at the authors' own claim ("We introduce..."),
    document passages at the first sentence that names the technique."""
    prose = re.sub(r"\\text\w*\{([^}]*)\}", r"\1", readable(text))  # \textbf{Re} -> Re
    if prose and not (prose[0].isupper() or prose[0] in "\"“("):
        cut = re.search(r"[.!?]\s+(?=[A-ZА-Я\"“(])", prose)  # the passage began mid-sentence: start at the next one
        prose = prose[cut.end():] if cut else ""
    parts, current = [], ""
    for piece in re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я\"“(])", prose):
        current = f"{current} {piece}".strip()
        if current.endswith(ABBR):
            continue  # "et al." is not a sentence end
        parts.append(current)
        current = ""
        if len(parts) == count + 4:
            break
    sentences = parts
    if len(parts) < count:  # keep reading: the window above may stop before enough sentences
        pass
    pick = None
    if focus:
        pick = next((i for i, p in enumerate(parts) if any(n.lower() in p.lower() for n in focus)), None)
        if pick is None:
            return ""  # no sentence names the technique: better no description than an unrelated one
    elif parts and not METHOD.search(parts[0]):
        pick = next((i for i, p in enumerate(parts[:4]) if METHOD.search(p)), None)
    if pick is not None:
        sentences = parts[pick:]
    out = ""
    for sentence in sentences[:count]:
        if len(out) + len(sentence) + 1 > limit and len(out) > 0:
            break
        out = f"{out} {sentence}".strip()
    return out if out.endswith((".", "!", "?", '."', ".”")) else ""


def cited_text(doc_pages: dict[int, str], start: int, end: int, names: list[str], limit: int = 2400) -> str:
    """Text around the technique on its cited pages, flowing over page breaks (page numbers removed)."""
    offsets, chunks, at = {}, [], 0
    for page in sorted(doc_pages):
        lines = doc_pages[page].splitlines()
        # A lone number low on the page starts the footnotes (or is the page number): drop from there.
        for i in range(int(len(lines) * 0.6), len(lines)):
            if re.fullmatch(r"\s*\d{1,3}\s*", lines[i]):
                lines = lines[:i]
                break
        body = "\n".join(l for l in lines if not re.fullmatch(r"\s*\d{1,3}\s*", l))
        offsets[page] = at
        chunks.append(body)
        at += len(body) + 1
    whole = "\n".join(chunks)
    lo = offsets.get(start, 0)
    hi = offsets.get(min(end, start + 3) + 1, len(whole))
    lower = whole.lower()
    for name in names:
        for match in re.finditer(re.escape(name.lower()), lower):
            if lo <= match.start() < hi:
                begin = max(lo, match.start() - 200)
                window = whole[begin:begin + limit]
                if "@misc{" in window[:400] or "http" in window[:240]:
                    continue
                return window
    return ""


def write_summaries(catalog: list, docs: dict[str, str]) -> int:
    """Add a 3-4 sentence description to every source in source-links.json:
    the opening of the abstract for arXiv papers (arXiv metadata is CC0), the cited passage for documents."""
    path = ROOT / "catalog" / "source-links.json"
    links = json.loads(path.read_text())
    abstracts = json.loads((ROOT / "catalog" / "arxiv-abstracts.json").read_text())
    by_key = {t["key"]: t for t in catalog}
    titles = {title_of(text): slug for slug, text in docs.items()}
    written = 0
    for key, sources in links.items():
        names = aliases(by_key[key]["name"], key) if key in by_key else [key.replace("_", " ")]
        for source in sources:
            arxiv = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", source.get("url", ""))
            text = WRITTEN_SUMMARIES.get((key, source.get("reference", "")), "")
            if text:
                pass
            elif arxiv and "arxiv.org/abs/" in source.get("url", "") and arxiv.group(1) in abstracts:  # abstract: own claim first
                text = summary(abstracts[arxiv.group(1)])
            else:
                slug = titles.get(source.get("title", "")) or (
                    "the-prompt-report-arxiv-2406.06608" if arxiv else None)
                ref = source.get("reference", "")
                numbers = [int(n) for n in re.findall(r"\d+", re.split(r"\bp\.", ref, maxsplit=1)[1])] if re.search(r"\bp\.", ref) else []
                if slug in docs and numbers:
                    pages = pages_of(docs[slug])
                    last = numbers[1] if len(numbers) > 1 else numbers[0]
                    text = summary(cited_text(pages, numbers[0], last, names), focus=names) or summary(
                        passage(pages, numbers[0], last, names), focus=names)
            if text:
                source["summary"] = text
                written += 1
            else:
                source.pop("summary", None)
    path.write_text(json.dumps(links, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written


def main() -> None:
    catalog = json.loads((ROOT / "catalog" / "catalog.json").read_text())["techniques"]
    links = json.loads((ROOT / "catalog" / "source-links.json").read_text())
    docs = {p.stem: p.read_text(encoding="utf-8") for p in MD.glob("*.md")}
    out: dict[str, dict] = {}
    for t in catalog:
        if t["status"] == "index-only":
            continue
        names = aliases(t["name"], t["key"])
        found = []
        for ref in t["source_ref"].split(";"):
            ref = ref.strip()
            slug = next((s for a, s in ABBREV.items() if ref.startswith(a)), None)
            numbers = [int(n) for n in re.findall(r"\d+", re.split(r"\bp\.", ref, maxsplit=1)[1])] if re.search(r"\bp\.", ref) else []
            if slug not in docs or not numbers:
                continue
            text = passage(pages_of(docs[slug]), numbers[0], numbers[1] if len(numbers) > 1 else numbers[0], names)
            if text and all(text != f["text"] for f in found):
                found.append({"source": title_of(docs[slug]), "ref": ref, "text": text})
        paper = next((s for s in links.get(t["key"], []) if "arxiv.org/abs/" in s.get("url", "")
                      and s.get("reference", "").startswith("original paper")), None)
        out[t["key"]] = {"excerpts": found[:2],
                         "paper": f'{paper["title"]} ({paper["reference"].removeprefix("original paper · ")})' if paper else ""}
    body = json.dumps(out, ensure_ascii=False, indent=1)
    (ROOT / "catalog" / "source-excerpts.ts").write_text(
        "// Generated by catalog/build_excerpts.py from archive-org-prompting/md and source-links.json. Do not edit.\n"
        "export type SourceExcerpt = { source: string; ref: string; text: string };\n"
        "export const sourceExcerpts: Record<string, { excerpts: SourceExcerpt[]; paper: string }> = "
        + body + ";\n", encoding="utf-8")
    written = write_summaries(catalog, docs)
    total = sum(len(v) for v in links.values())
    print(f"source descriptions: {written} of {total}")
    empty = [k for k, v in out.items() if not v["excerpts"]]
    print(f"{len(out)} techniques, {sum(len(v['excerpts']) for v in out.values())} passages; without passage: {empty}")


if __name__ == "__main__":
    main()
