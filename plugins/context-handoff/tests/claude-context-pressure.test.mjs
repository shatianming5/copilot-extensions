import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { contextWindow, nudge } from "../hooks/context-pressure.mjs";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "ch-pressure-"));
  mkdirSync(join(root, ".git"));
  const transcript = join(root, "t.jsonl");
  const at = (tokens, opts = {}) => {
    writeFileSync(transcript, JSON.stringify({
      type: "assistant", message: { model: "m", usage: { input_tokens: tokens } },
    }) + "\n");
    return nudge({ session_id: "s", cwd: root, transcript_path: transcript },
      { env: { CONTEXT_HANDOFF_TOKEN_LIMIT: "1000" }, stateDir: join(root, "state"), ...opts });
  };
  return { root, at };
}

test("context window: env override, then Claude Code's model catalog", () => {
  assert.equal(contextWindow("claude-opus-5-5", {}), 1_000_000);
  assert.equal(contextWindow("claude-sonnet-4-6", {}), 200_000);
  assert.equal(contextWindow("claude-sonnet-4-6[1m]", {}), 1_000_000);
  assert.equal(contextWindow("claude-opus-5-5", { CLAUDE_CODE_DISABLE_1M_CONTEXT: "1" }), 200_000);
  assert.equal(contextWindow("claude-opus-5-5", { CLAUDE_CODE_MAX_CONTEXT_TOKENS: "256000" }), 256_000);
});

test("nudges once per level, hard covers soft, re-arms below soft", () => {
  const { at } = fixture();
  assert.equal(at(100), "");
  assert.match(at(600), /soft threshold/);
  assert.equal(at(650), "");
  assert.match(at(800), /hard threshold/);
  assert.equal(at(600), "");
  assert.equal(at(100), "");
  assert.match(at(600), /soft threshold/);
});

test("repository config: thresholds apply and mode: off silences the nudge", () => {
  const { root, at } = fixture();
  mkdirSync(join(root, ".context-handoff"));
  writeFileSync(join(root, ".context-handoff", "config.yaml"),
    "thresholds:\n  soft_percent: 40\n  hard_percent: 60\n");
  assert.match(at(450), /soft threshold/);
  writeFileSync(join(root, ".context-handoff", "config.yaml"), "mode: off\n");
  assert.equal(at(900), "");
});
