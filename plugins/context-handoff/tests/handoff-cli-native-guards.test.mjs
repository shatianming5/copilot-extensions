import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const cli = new URL(
  "../extensions/context-handoff/handoff-cli.mjs",
  import.meta.url,
);

test("SDK-free save refuses a session with a native objective", () => {
  const home = mkdtempSync(join(process.cwd(), ".test-handoff-cli-save-"));
  const sid = "session-native";
  const state = join(home, "session-state", sid);
  mkdirSync(state, { recursive: true });
  writeFileSync(
    join(state, "autopilot-objective.json"),
    JSON.stringify({ version: 1, current: { status: "active" } }),
  );
  try {
    const result = spawnSync(
      process.execPath,
      [
        cli.pathname,
        "save",
        "--prompt", "continue",
        "--session-id", sid,
        "--cwd", home,
        "--no-task",
      ],
      {
        encoding: "utf-8",
        env: { ...process.env, COPILOT_HOME: home },
      },
    );
    assert.equal(result.status, 1);
    assert.match(result.stderr, /cannot transfer native mode and permissions/);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("SDK-free consume leaves a native baton unconsumed", () => {
  const home = mkdtempSync(join(process.cwd(), ".test-handoff-cli-consume-"));
  const baton = join(home, "handoff.json");
  writeFileSync(baton, JSON.stringify({
    kind: "context-handoff",
    id: "handoff-native",
    consumed: false,
    promptText: "continue",
    nativeContinuation: {
      version: 1,
      mode: "autopilot",
      permissionMode: "manual",
      autopilotObjective: "{\"version\":1}",
    },
  }));
  try {
    const result = spawnSync(
      process.execPath,
      [
        cli.pathname,
        "consume",
        "--path", baton,
        "--session-id", "successor",
        "--cwd", home,
      ],
      { encoding: "utf-8", env: { ...process.env, COPILOT_HOME: home } },
    );
    assert.equal(result.status, 1);
    assert.match(result.stderr, /must be consumed by the in-session extension/);
    assert.equal(JSON.parse(readFileSync(baton, "utf-8")).consumed, false);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

for (const command of ["trigger", "retry-cutover"]) {
  test(`SDK-free ${command} launches nothing for a session with a native objective`, () => {
    const home = mkdtempSync(join(process.cwd(), `.test-handoff-cli-${command}-`));
    const sid = "session-native";
    const state = join(home, "session-state", sid);
    mkdirSync(state, { recursive: true });
    writeFileSync(
      join(state, "autopilot-objective.json"),
      JSON.stringify({ version: 1, current: { status: "active" } }),
    );
    try {
      const result = spawnSync(
        process.execPath,
        [cli.pathname, command, "--prompt", "continue", "--session-id", sid,
          "--cwd", home, "--no-task"],
        { encoding: "utf-8", env: { ...process.env, COPILOT_HOME: home } },
      );
      assert.equal(result.status, 1);
      assert.match(result.stderr, /in-session extension/);
      assert.match(result.stderr, /Nothing was (written or )?launched/);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
}
