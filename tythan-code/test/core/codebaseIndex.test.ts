import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildFileMap,
  expandCodebaseMention,
  retrieveSnippets,
  tokenize,
} from "../../src/core/codebaseIndex";
import { Workspace } from "../../src/core/tools";

let tmpDir: string;
let ws: Workspace;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tythan-code-index-"));
  ws = new Workspace(tmpDir);
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function write(rel: string, content: string): void {
  const target = path.join(tmpDir, rel);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
}

describe("tokenize", () => {
  it("splits camelCase and snake_case identifiers", () => {
    expect(tokenize("getUserProfile")).toEqual(["get", "user", "profile"]);
    expect(tokenize("get_user_profile")).toEqual(["get", "user", "profile"]);
  });

  it("drops stopwords and short tokens", () => {
    expect(tokenize("how does the db work")).toEqual(["work"]);
  });
});

describe("retrieveSnippets", () => {
  it("ranks the file about the query topic first", () => {
    write(
      "src/auth.py",
      [
        "def hash_password(password):",
        "    return bcrypt.hash(password)",
        "",
        "def authenticate_user(username, password):",
        '    """Check the login credentials against the database."""',
        "    user = find_user(username)",
        "    return user and verify_password(user, password)",
      ].join("\n"),
    );
    write("src/billing.py", "def charge_card(amount):\n    return stripe.charge(amount)\n");
    write("README.md", "# Demo project\n");

    const snippets = retrieveSnippets(ws, "where is user authentication and password login handled?");
    expect(snippets.length).toBeGreaterThan(0);
    expect(snippets[0]?.path).toBe("src/auth.py");
    expect(snippets[0]?.text).toContain("authenticate_user");
  });

  it("matches identifier queries against camelCase code", () => {
    write("src/profile.ts", "export function getUserProfile(id: string) {\n  return db.load(id);\n}\n");
    write("src/other.ts", "export const unrelated = 42;\n");
    const snippets = retrieveSnippets(ws, "user profile loading");
    expect(snippets[0]?.path).toBe("src/profile.ts");
  });

  it("returns [] for an empty/stopword-only query", () => {
    write("a.ts", "const x = 1;");
    expect(retrieveSnippets(ws, "the and for")).toEqual([]);
  });

  it("returns [] for an empty workspace", () => {
    expect(retrieveSnippets(ws, "anything interesting")).toEqual([]);
  });

  it("caps snippets per file at 2 for breadth", () => {
    const big = Array.from({ length: 30 }, (_, i) => `function persistence_${i}() { /* persistence layer */ }`).join(
      "\n".repeat(5),
    );
    write("src/persistence.ts", big);
    write("src/persistence2.ts", "// persistence helper\nexport const persistence = true;\n");
    const snippets = retrieveSnippets(ws, "persistence layer");
    const fromBig = snippets.filter((s) => s.path === "src/persistence.ts");
    expect(fromBig.length).toBeLessThanOrEqual(2);
  });
});

describe("buildFileMap", () => {
  it("lists workspace files", () => {
    write("src/a.ts", "x");
    write("src/b.ts", "y");
    const map = buildFileMap(ws);
    expect(map).toContain("src/a.ts");
    expect(map).toContain("src/b.ts");
  });
});

describe("expandCodebaseMention", () => {
  it("returns text unchanged without an @codebase mention", () => {
    write("a.ts", "const x = 1;");
    expect(expandCodebaseMention("plain question", ws)).toBe("plain question");
  });

  it("does not fire on an email-like or mid-word mention", () => {
    expect(expandCodebaseMention("mail me@codebase.com", ws)).toBe("mail me@codebase.com");
  });

  it("appends file map and snippets for @codebase", () => {
    write("src/auth.py", "def authenticate_user(username, password):\n    return check(username, password)\n");
    const expanded = expandCodebaseMention("@codebase where is user authentication handled?", ws);
    expect(expanded).toContain("<codebase-context");
    expect(expanded).toContain("<file-map>");
    expect(expanded).toContain("src/auth.py");
    expect(expanded).toContain("authenticate_user");
    expect(expanded.startsWith("@codebase where is")).toBe(true);
  });

  it("uses the separate raw query when provided", () => {
    write("src/auth.py", "def authenticate_user():\n    pass\n");
    // `text` (already expanded elsewhere) has no @codebase; the raw query does.
    const expanded = expandCodebaseMention("expanded text without mention", ws, "@codebase authentication user");
    expect(expanded).toContain("<codebase-context");
  });
});
