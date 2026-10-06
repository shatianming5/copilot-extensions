#!/usr/bin/env node
// Claude Code PostToolUse hook: the extension's context-pressure nudge.
//
// Copilot's context-handoff extension watches session.usage_info and nudges at
// the soft and hard thresholds. Claude Code has no extension, so this hook reads
// the input tokens of the latest main-thread assistant turn from the transcript
// and sends the same nudge, once per level; dropping back below soft (after
// /compact) re-arms both. Thresholds and mode come from the same config.mjs /
// thresholds.mjs / mode.mjs the extension uses (repo and user config.yaml).
//
// Hooks are not told the context window: CONTEXT_HANDOFF_TOKEN_LIMIT, else
// Claude Code's CLAUDE_CODE_MAX_CONTEXT_TOKENS, else the model's window per
// Claude Code's catalog (200k for the families below, 1M for the rest and for
// "[1m]" ids). Grok's hook payload has no transcript, so this is a no-op there.

import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { loadContextHandoffConfig } from "../extensions/context-handoff/config.mjs";
import { automaticPressureHandlingEnabled } from "../extensions/context-handoff/mode.mjs";
import { contextPressure, formatContextUsage } from "../extensions/context-handoff/thresholds.mjs";

const STATE_DIR = join(homedir(), ".cache", "context-handoff", "claude-pressure");
// Model ids Claude Code's catalog gives a 200k window; its other models are 1M.
const WINDOW_200K = ["claude-3", "claude-haiku", "claude-sonnet-4", "claude-opus-4-0",
  "claude-opus-4-1", "claude-opus-4-2025", "claude-opus-4-5", "claude-opus-4-6"];

export function contextWindow(model, env = process.env) {
  for (const name of ["CONTEXT_HANDOFF_TOKEN_LIMIT", "CLAUDE_CODE_MAX_CONTEXT_TOKENS"]) {
    if (env[name]) return Number.parseInt(env[name], 10);
  }
  const id = String(model || "").toLowerCase();
  if (!id.includes("[1m]") && (env.CLAUDE_CODE_DISABLE_1M_CONTEXT
      || WINDOW_200K.some(prefix => id.startsWith(prefix)))) {
    return 200_000;
  }
  return 1_000_000;
}

// Input tokens of the latest main-thread assistant turn, and its model.
export function contextTokens(transcript) {
  const size = statSync(transcript).size;
  const length = Math.min(size, 2_000_000);
  const buffer = Buffer.alloc(length);
  const fd = openSync(transcript, "r");
  try { readSync(fd, buffer, 0, length, size - length); } finally { closeSync(fd); }
  const lines = buffer.toString("utf8").split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    let entry;
    try { entry = JSON.parse(lines[i]); } catch { continue; }
    const usage = entry?.message?.usage;
    if (entry?.type !== "assistant" || entry.isSidechain || !usage) continue;
    const tokens = ["input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"]
      .reduce((sum, key) => sum + (Number(usage[key]) || 0), 0);
    return { tokens, model: entry.message.model || "" };
  }
  return { tokens: 0, model: "" };
}

// The nudge due for this PostToolUse ("" when none); records the level sent.
export function nudge(payload, { env = process.env, stateDir = STATE_DIR } = {}) {
  const transcript = payload?.transcript_path || "";
  if (!transcript || !existsSync(transcript)) return "";
  const config = loadContextHandoffConfig(payload.cwd || process.cwd());
  if (!automaticPressureHandlingEnabled(config.mode)) return "";
  const { tokens, model } = contextTokens(transcript);
  const limit = contextWindow(model, env);
  const pressure = contextPressure(tokens, limit, config.thresholds);
  const level = pressure.hard ? "hard" : pressure.soft ? "soft" : "";
  const state = join(stateDir, String(payload.session_id || "unknown"));
  const sent = existsSync(state) ? readFileSync(state, "utf8").trim() : "";
  if (level === sent || (sent === "hard" && level === "soft")) return "";
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(state, level);
  if (!level) return "";
  const usage = formatContextUsage(tokens, limit);
  return level === "hard"
    ? `[Context Handoff -- automated] Context utilization is ${usage.utilization} ` +
      `(${usage.tokens}). The configured hard threshold was reached; auto-compaction ` +
      "still triggers at ~80%. Invoke the context-handoff skill now to preserve " +
      "continuity before context is lost. Compose/store the baton and then call " +
      "trigger_handoff directly; do not pause to ask the user first."
    : `[Context Handoff -- automated] Context utilization is ${usage.utilization} ` +
      `(${usage.tokens}). The configured soft threshold was reached. Invoke the ` +
      "context-handoff skill at the next clean boundary so you can compose/store a " +
      "baton early and, if work still remains, trigger_handoff directly before the " +
      "window gets tighter.";
}

if (import.meta.url === `file://${process.argv[1]}`) {
  let message = "";
  try {
    message = nudge(JSON.parse(readFileSync(0, "utf8") || "{}"));
  } catch {
    // A hook must never break the session.
  }
  if (message) {
    process.stdout.write(JSON.stringify({ hookSpecificOutput: {
      hookEventName: "PostToolUse", additionalContext: message } }));
  }
}
