import test from "node:test";
import assert from "node:assert/strict";
import { isGrokHost } from "../extensions/context-handoff/herdr.mjs";

const KEYS = ["COPILOT_AGENT_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
  "GROK_SESSION_ID", "GROK_PANE", "GROK_HOME"];

function withEnv(env, fn) {
  const saved = Object.fromEntries(KEYS.map(k => [k, process.env[k]]));
  for (const k of KEYS) delete process.env[k];
  Object.assign(process.env, env);
  try { return fn(); } finally {
    for (const k of KEYS) {
      if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k];
    }
  }
}

test("Grok markers leaked into a Copilot or Claude session do not make it Grok", () => {
  assert.equal(withEnv({ GROK_SESSION_ID: "g" }, isGrokHost), true);
  assert.equal(withEnv({ GROK_PANE: "1" }, isGrokHost), true);
  assert.equal(withEnv({ GROK_HOME: "/h/.grok" }, isGrokHost), false);
  assert.equal(withEnv({ GROK_PANE: "1", GROK_HOME: "/h", COPILOT_AGENT_SESSION_ID: "c" }, isGrokHost), false);
  assert.equal(withEnv({ GROK_PANE: "1", CLAUDECODE: "1" }, isGrokHost), false);
});
