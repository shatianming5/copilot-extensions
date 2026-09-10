import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import vm from "node:vm";
import {
  consumeFileHandoff, nativeHandoffConsumeError, writeJsonAtomic,
  runHerdrHandoffCutover,
} from "../extensions/context-handoff/handoff-core.mjs";

test("fork file admission rejects unhydrated and legacy batons before consuming", () => {
  const dir = mkdtempSync(join(tmpdir(), "native-fork-"));
  try {
    const checkpoint = join(dir, "checkpoint.json");
    const path = join(dir, "baton.json");
    const metadata = {
      kind: "context-handoff", id: "token", sessionId: "source",
      nativeGoalCheckpoint: checkpoint, promptText: "Owned progress", consumed: false,
    };
    const request = {
      kind: "context-handoff-session-request", sessionId: "source", handoffId: "token",
      nativeGoal: { version: 1, phase: "prepared", successorSessionId: "target", intent: "stopped" },
    };
    writeJsonAtomic(checkpoint, request);
    writeJsonAtomic(path, metadata);
    assert.match(consumeFileHandoff(dir, "target", "token", path).message, /restoration is pending/);
    assert.equal(JSON.parse(readFileSync(path)).consumed, false);
    for (const legacy of ["nativeContinuation", "nativeState"]) {
      assert.match(nativeHandoffConsumeError({ [legacy]: { version: 1 } }, "target", "token"), /Legacy native/);
    }
    request.nativeGoal.hydratedBySession = "target";
    request.nativeGoal.phase = "hydrated";
    writeJsonAtomic(checkpoint, request);
    assert.equal(consumeFileHandoff(dir, "target", "token", path).ok, true);
    assert.equal(consumeFileHandoff(dir, "target", "token", path).ok, true);
    assert.equal(consumeFileHandoff(dir, "other", "token", path).ok, false);
    assert.equal(JSON.parse(readFileSync(checkpoint)).nativeGoal.consumedBySession, "target");

    const cli = new URL("../extensions/context-handoff/handoff-cli.mjs", import.meta.url);
    const direct = spawnSync(process.execPath, [cli.pathname, "consume", "--path", path, "--session-id", "target"], {
      encoding: "utf8", env: { ...process.env, COPILOT_HOME: dir },
    });
    assert.equal(direct.status, 1);
    assert.match(direct.stderr, /native session state/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("native Herdr adapter passes launcher contract and preserves unknown outcomes", () => {
  const home = mkdtempSync(join(tmpdir(), "native-herdr-"));
  try {
    const options = {
      home, env: { HERDR_ENV: "1", HERDR_PANE_ID: "owned-source" },
      permissionMode: "allow-all",
      native: { checkpoint: "/owned/checkpoint", launcher: "/owned/native-launch.mjs" },
    };
    let launched = 0;
    const execute = (bin, args) => {
      if (bin.endsWith("/herdr")) return JSON.stringify({ result: { pane: { cwd: home } } });
      launched++;
      assert.deepEqual(args.slice(-4), [
        "--native-handoff", "/owned/checkpoint", "--native-launcher", "/owned/native-launch.mjs",
      ]);
      return "pane_handle=owned-target\ncopilot_session_id=target\nstartup_pending=true\n";
    };
    assert.equal(runHerdrHandoffCutover(home, "seed", "source", { ...options, execute }).startup_pending, true);
    assert.equal(launched, 1);
    assert.throws(() => runHerdrHandoffCutover(home, "seed", "source", {
      ...options, execute: (bin, args) => bin.endsWith("/herdr") ? execute(bin, args) : "",
    }), /unresolved/);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("fork mux retirement checks exact bind/head after admission, never a candidate", () => {
  const source = readFileSync(new URL("../extensions/context-handoff/native-runtime.mjs", import.meta.url), "utf8")
    .replace(/^import[\s\S]*?from "[^"]+";\n/gm, "").replaceAll("export ", "");
  let record = {
    kind: "context-handoff-session-request", sessionId: "source", handoffId: "token",
    worktree: "owned", worktreeDir: "/owned", consumed: true,
    nativeGoal: {
      successorSessionId: "target", hydratedBySession: "target", intent: "running",
      launchTransport: "mux", launch: { old_pane: "%1", new_pane: "%2", session: "wt-owned" },
    },
  };
  const calls = [];
  let head = "target";
  const context = vm.createContext({
    readFileSync: () => JSON.stringify(record),
    writeJsonAtomic: (_path, value) => { record = structuredClone(value); },
    runCli: (_bin, args) => {
      calls.push(args);
      return JSON.stringify(args[0] === "bind-session"
        ? { bound: true, session: "target", head_session: head }
        : { ok: true, gone: true });
    },
  });
  vm.runInContext(`${source}\nglobalThis.retire = retireNativePredecessor;`, context);
  assert.throws(() => context.retire("checkpoint", "target"), /admission is incomplete/);
  assert.equal(calls.length, 0);
  record.nativeGoal.continuationObserved = "owned-message";
  head = "different";
  assert.throws(() => context.retire("checkpoint", "target"), /acknowledged worktree head/);
  assert.equal(calls.filter(args => args[0] === "handoff-cutover").length, 0);
  head = "target";
  context.retire("checkpoint", "target");
  const retireArgs = calls.at(-1);
  assert.equal(retireArgs[retireArgs.indexOf("--session-id") + 1], "source");
  assert.equal(retireArgs[retireArgs.indexOf("--mux-session") + 1], "wt-owned");
  assert.ok(retireArgs.includes("--require-mux-identity"));
  context.retire("checkpoint", "target");
  assert.equal(calls.filter(args => args[0] === "handoff-cutover").length, 1);
});
