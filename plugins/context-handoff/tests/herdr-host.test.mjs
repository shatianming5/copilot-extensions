import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { isGrokHost, launchHerdrSuccessor } from "../extensions/context-handoff/herdr.mjs";
import { nativeLaunchArguments, isGrokCli } from "../extensions/context-handoff/native-launch.mjs";

function withEnv(values, fn) {
  const keys = Object.keys(values);
  const before = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  try {
    for (const [key, value] of Object.entries(values)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    return fn();
  } finally {
    for (const key of keys) {
      if (before[key] === undefined) delete process.env[key];
      else process.env[key] = before[key];
    }
  }
}

test("GROK_SESSION_ID selects the Grok Herdr host", () => {
  withEnv({
    GROK_SESSION_ID: "owned-grok",
    GROK_PANE: undefined,
    GROK_HOME: undefined,
    COPILOT_AGENT_SESSION_ID: undefined,
  }, () => {
    assert.equal(isGrokHost(), true);
  });
});

test("COPILOT_AGENT_SESSION_ID without Grok identity stays Copilot", () => {
  withEnv({
    GROK_SESSION_ID: undefined,
    GROK_PANE: undefined,
    GROK_HOME: undefined,
    COPILOT_AGENT_SESSION_ID: "owned-copilot",
  }, () => {
    assert.equal(isGrokHost(), false);
  });
});

test("Grok Herdr successor launches grok-pane, not copilot-pane", () => {
  const cwd = mkdtempSync(join(tmpdir(), "grok-herdr-"));
  try {
    withEnv({
      GROK_SESSION_ID: "owned-grok",
      GROK_PANE: undefined,
      GROK_HOME: undefined,
      COPILOT_AGENT_SESSION_ID: undefined,
      HERDR_ENV: "1",
      HERDR_PANE_ID: "w1:p1",
    }, () => {
      const calls = [];
      const result = launchHerdrSuccessor(cwd, "continue the Grok work", (command, args) => {
        calls.push({ command, args });
        if (String(command).endsWith("herdr") && args[0] === "pane") {
          return JSON.stringify({ result: { pane: { cwd } } });
        }
        if (String(command).endsWith("grok-pane")) {
          assert.equal(args[0], "launch");
          assert.ok(!String(command).includes("copilot-pane"));
          return [
            "pane_handle=w1:p2",
            "grok_session_id=aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "startup_pending=false",
          ].join("\n");
        }
        throw new Error(`unexpected command ${command} ${args.join(" ")}`);
      }, "always-approve");
      assert.equal(result.ok, true);
      assert.equal(result.new_pane, "w1:p2");
      assert.equal(result.new_session, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee");
      assert.equal(calls.filter(call => String(call.command).endsWith("grok-pane")).length, 1);
      assert.equal(calls.filter(call => String(call.command).endsWith("copilot-pane")).length, 0);
    });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("Copilot Herdr successor still launches copilot-pane", () => {
  const cwd = mkdtempSync(join(tmpdir(), "copilot-herdr-"));
  try {
    withEnv({
      GROK_SESSION_ID: undefined,
      GROK_PANE: undefined,
      GROK_HOME: undefined,
      COPILOT_AGENT_SESSION_ID: "owned-copilot",
      HERDR_ENV: "1",
      HERDR_PANE_ID: "w1:p1",
    }, () => {
      const calls = [];
      const result = launchHerdrSuccessor(cwd, "continue the Copilot work", (command, args) => {
        calls.push({ command, args });
        if (String(command).endsWith("herdr") && args[0] === "pane") {
          return JSON.stringify({ result: { pane: { cwd } } });
        }
        if (String(command).endsWith("copilot-pane")) {
          return [
            "pane_handle=w1:p9",
            "copilot_session_id=bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
            "startup_pending=false",
          ].join("\n");
        }
        throw new Error(`unexpected command ${command} ${args.join(" ")}`);
      }, "allow-all");
      assert.equal(result.new_session, "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff");
      assert.equal(calls.filter(call => String(call.command).endsWith("copilot-pane")).length, 1);
      assert.equal(calls.filter(call => String(call.command).endsWith("grok-pane")).length, 0);
    });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("Grok native launch arguments use --always-approve and skip Copilot-only flags", () => {
  assert.equal(isGrokCli("/home/ubuntu/.grok/bin/grok"), true);
  assert.equal(isGrokCli("/home/ubuntu/.local/lib/agent-env/copilot-wrapper/copilot"), false);
  const record = {
    handoffId: "handoff-source",
    seed: "Consume the existing baton",
    nativeGoal: { successorSessionId: "target", permissionMode: "always-approve" },
  };
  const args = nativeLaunchArguments(record, "prepare", ["--session-id", "target", "--always-approve"], { grok: true });
  assert.ok(args.includes("--always-approve"));
  assert.ok(!args.includes("--mode"));
  assert.ok(!args.includes("--name"));
  assert.ok(!args.includes("--allow-all"));
  assert.deepEqual(args.slice(-3), ["--session-id", "target", "--always-approve"]);
});
