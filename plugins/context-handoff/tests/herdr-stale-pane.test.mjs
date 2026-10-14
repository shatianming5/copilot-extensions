import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { isHerdrPane, resolveHerdrCwd } from "../extensions/context-handoff/herdr.mjs";
import { installFakeHerdr } from "./fixtures/fake-herdr.mjs";

function withFakeHerdr(paneId, fn) {
  const home = mkdtempSync(join(tmpdir(), "herdr-stale-"));
  const keys = ["HOME", "HERDR_ENV", "HERDR_PANE_ID"];
  const before = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  installFakeHerdr(home, "w1:live");
  Object.assign(process.env, { HOME: home, HERDR_ENV: "1", HERDR_PANE_ID: paneId });
  try {
    return fn(home);
  } finally {
    for (const key of keys) {
      if (before[key] === undefined) delete process.env[key];
      else process.env[key] = before[key];
    }
    rmSync(home, { recursive: true, force: true });
  }
}

test("inherited HERDR env for a closed pane falls back to the non-Herdr path", () => {
  withFakeHerdr("w7:gone", home => {
    assert.equal(isHerdrPane(), false);
    assert.equal(resolveHerdrCwd(home, () => assert.fail("must not ask Herdr for the current pane")), home);
  });
});

test("a live Herdr pane keeps the Herdr path", () => {
  withFakeHerdr("w1:live", home => {
    assert.equal(isHerdrPane(), true);
    const cwd = resolveHerdrCwd(home, (command, args) => {
      assert.ok(String(command).endsWith("herdr"));
      assert.deepEqual(args, ["pane", "current", "--current"]);
      return JSON.stringify({ result: { pane: { cwd: "/pane/cwd" } } });
    });
    assert.equal(cwd, "/pane/cwd");
  });
});

test("a missing herdr binary is not a Herdr pane", () => {
  const home = mkdtempSync(join(tmpdir(), "herdr-missing-"));
  const keys = ["HOME", "HERDR_ENV", "HERDR_PANE_ID"];
  const before = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  Object.assign(process.env, { HOME: home, HERDR_ENV: "1", HERDR_PANE_ID: "w1:live" });
  try {
    assert.equal(isHerdrPane(), false);
  } finally {
    for (const key of keys) {
      if (before[key] === undefined) delete process.env[key];
      else process.env[key] = before[key];
    }
    rmSync(home, { recursive: true, force: true });
  }
});
