/**
 * @codebase context retrieval — offline lexical search over the workspace.
 *
 * Honest scope: this is TF-IDF-style ranking over line chunks, not the
 * embedding index a hosted product builds server-side. It needs no network,
 * no index build step and no storage, and in practice pointing the model at
 * the top-scoring chunks plus a file map answers "where is X handled?"
 * questions well. Identifier-aware tokenization (camelCase / snake_case
 * splitting) keeps code queries from missing `getUserProfile` when the user
 * asks about "user profile".
 */

import * as path from "node:path";

import { Workspace, truncate } from "./tools";

export const CODEBASE_MENTION_RX = /(^|\s)@codebase\b/;

const CHUNK_LINES = 40;
const CHUNK_OVERLAP = 10;
const MAX_FILES = 4_000;
const MAX_FILE_CHARS = 200_000;
const TOP_SNIPPETS = 8;
const MAX_CONTEXT_CHARS = 14_000;
const MAX_FILE_MAP_ENTRIES = 250;

// File types worth indexing for retrieval.
const INDEX_SUFFIXES = new Set([
  ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rb", ".php",
  ".java", ".kt", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".swift",
  ".sh", ".bash", ".zsh", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
  ".md", ".txt", ".html", ".css", ".vue", ".svelte", ".sql", ".proto",
]);

const STOPWORDS = new Set([
  "the", "and", "for", "with", "that", "this", "from", "are", "was", "how",
  "what", "where", "when", "can", "does", "into", "use", "used", "using",
  "codebase", "file", "files", "code", "please", "add", "make", "new",
]);

export interface CodeSnippet {
  path: string;
  startLine: number;
  endLine: number;
  text: string;
  score: number;
}

/** Split text into search terms, breaking identifiers apart: `getUserProfile`
 * and `get_user_profile` both yield [get, user, profile]. */
export function tokenize(text: string): string[] {
  const words = text.match(/[A-Za-z][A-Za-z0-9]*|[0-9]+/g) ?? [];
  const out: string[] = [];
  for (const word of words) {
    // split camelCase / PascalCase boundaries
    const parts = word.replace(/([a-z0-9])([A-Z])/g, "$1 $2").split(/\s+/);
    for (const part of parts) {
      const lower = part.toLowerCase();
      if (lower.length >= 3 && !STOPWORDS.has(lower)) {
        out.push(lower);
      }
    }
  }
  return out;
}

interface Chunk {
  rel: string;
  startLine: number;
  endLine: number;
  text: string;
  terms: Map<string, number>;
}

function chunkFile(rel: string, text: string): Chunk[] {
  const lines = text.split(/\r\n|\r|\n/);
  const chunks: Chunk[] = [];
  for (let start = 0; start < lines.length; start += CHUNK_LINES - CHUNK_OVERLAP) {
    const window = lines.slice(start, start + CHUNK_LINES);
    if (window.every((l) => !l.trim())) {
      continue;
    }
    const chunkText = window.join("\n");
    const terms = new Map<string, number>();
    for (const term of tokenize(chunkText)) {
      terms.set(term, (terms.get(term) ?? 0) + 1);
    }
    chunks.push({ rel, startLine: start + 1, endLine: start + window.length, text: chunkText, terms });
    if (start + CHUNK_LINES >= lines.length) {
      break;
    }
  }
  return chunks;
}

/** Retrieve the workspace chunks most relevant to `query`, TF-IDF ranked. */
export function retrieveSnippets(ws: Workspace, query: string, topK: number = TOP_SNIPPETS): CodeSnippet[] {
  const queryTerms = [...new Set(tokenize(query))];
  if (queryTerms.length === 0) {
    return [];
  }

  const chunks: Chunk[] = [];
  const docFreq = new Map<string, number>();
  let fileCount = 0;
  for (const rel of listIndexableFiles(ws)) {
    let plain: string;
    try {
      plain = ws.readRaw(rel);
    } catch {
      continue;
    }
    if (plain.length > MAX_FILE_CHARS || plain.slice(0, 1024).includes("\0")) {
      continue;
    }
    fileCount++;
    const fileTerms = new Set<string>();
    for (const chunk of chunkFile(rel, plain)) {
      chunks.push(chunk);
      for (const term of chunk.terms.keys()) {
        fileTerms.add(term);
      }
    }
    for (const term of fileTerms) {
      if (queryTerms.includes(term)) {
        docFreq.set(term, (docFreq.get(term) ?? 0) + 1);
      }
    }
  }
  if (fileCount === 0) {
    return [];
  }

  const idf = new Map<string, number>();
  for (const term of queryTerms) {
    const df = docFreq.get(term) ?? 0;
    idf.set(term, Math.log(1 + (fileCount + 1) / (df + 1)));
  }

  const scored = chunks
    .map((chunk) => {
      let score = 0;
      let matched = 0;
      for (const term of queryTerms) {
        const tf = chunk.terms.get(term) ?? 0;
        if (tf > 0) {
          matched++;
          score += (1 + Math.log(tf)) * (idf.get(term) ?? 0);
        }
      }
      // Reward chunks matching *several* distinct query terms over chunks
      // repeating one common term many times.
      score *= matched;
      return { chunk, score };
    })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score);

  const out: CodeSnippet[] = [];
  const perFile = new Map<string, number>();
  for (const { chunk, score } of scored) {
    const used = perFile.get(chunk.rel) ?? 0;
    if (used >= 2) {
      continue; // at most 2 chunks per file, for breadth
    }
    perFile.set(chunk.rel, used + 1);
    out.push({ path: chunk.rel, startLine: chunk.startLine, endLine: chunk.endLine, text: chunk.text, score });
    if (out.length >= topK) {
      break;
    }
  }
  return out;
}

function listIndexableFiles(ws: Workspace): string[] {
  const listing = ws.listFiles("**/*");
  if (listing.startsWith("(no files")) {
    return [];
  }
  return listing
    .split("\n")
    .filter((rel) => !rel.startsWith("... ["))
    .filter((rel) => INDEX_SUFFIXES.has(path.extname(rel).toLowerCase()))
    .slice(0, MAX_FILES);
}

/** Compact file map of the project — gives the model the lay of the land. */
export function buildFileMap(ws: Workspace): string {
  const listing = ws.listFiles("**/*");
  if (listing.startsWith("(no files")) {
    return "(empty workspace)";
  }
  const files = listing.split("\n").filter((rel) => !rel.startsWith("... ["));
  const shown = files.slice(0, MAX_FILE_MAP_ENTRIES);
  const omitted = files.length - shown.length;
  return shown.join("\n") + (omitted > 0 ? `\n... [${omitted} more files]` : "");
}

/** When `text` mentions @codebase, append a retrieved-context block (file map
 * + top-scoring snippets for the message) and return the expanded text;
 * otherwise return `text` unchanged. `query` defaults to the text itself. */
export function expandCodebaseMention(text: string, ws: Workspace, query?: string): string {
  if (!CODEBASE_MENTION_RX.test(query ?? text)) {
    return text;
  }
  const q = query ?? text;
  const snippets = retrieveSnippets(ws, q);
  const parts: string[] = [`<codebase-context note="retrieved for the @codebase mention; may be incomplete">`];
  parts.push(`<file-map>\n${buildFileMap(ws)}\n</file-map>`);
  let used = 0;
  for (const s of snippets) {
    const block = `<snippet path="${s.path}" lines="${s.startLine}-${s.endLine}">\n${truncate(s.text, 4000)}\n</snippet>`;
    if (used + block.length > MAX_CONTEXT_CHARS) {
      break;
    }
    used += block.length;
    parts.push(block);
  }
  parts.push(`</codebase-context>`);
  return `${text}\n\n${parts.join("\n")}`;
}
