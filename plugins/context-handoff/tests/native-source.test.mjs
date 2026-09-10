import assert from "node:assert/strict";
import { test } from "node:test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import vm from "node:vm";

// Exercise the actual caller AND core's execFileSync path. Only the executable
// locator is replaced: an owned Node child emits the mux CLI protocol and exits.
const core = readFileSync(new URL(
  "../extensions/context-handoff/handoff-core.mjs", import.meta.url,
), "utf8");
const runCliSource = core.slice(core.indexOf("export function runCli("),
  core.indexOf("// True if an agent-dispatch")).replace("export ", "");
const source = readFileSync(new URL(
  "../extensions/context-handoff/native-source.mjs", import.meta.url,
), "utf8").replace(/^import[\s\S]*?from "[^"]+";\n/gm, "")
  .replaceAll("export ", "").replace("import.meta.url", '"file:///owned/native-source.mjs"');

function fixture({ status = 0, output = '{"ok":true,"new_pane":"%5"}',
  permissionMode = "allow-all", herdr = false, plain = false, onExit = () => {} } = {}) {
  let record = {
    sessionId: "source", handoffId: "token", seed: "owned seed",
    nativeGoal: {
      phase: "frozen", sourceObjectiveId: null, successorSessionId: "target",
      cwd: process.cwd(), permissionMode,
    },
  };
  if (plain) record = {
    ...record, nativeGoal: null, permissionMode, cwd: process.cwd(), promptText: "Owned plain brief",
  };
  const pending = {
    seed: record.seed, promptText: "Owned plain brief",
    stored: { id: "token", storage: "file", path: "baton", metadata: {} },
  };
  const calls = [];
  const pauses = [];
  const context = vm.createContext({
    process, JSON, dirname: () => "/owned", join: (...parts) => parts.join("/"),
    fileURLToPath: value => value,
    execFileSync: (bin, args, options) => {
      calls.push({ bin, args });
      try {
        return execFileSync(process.execPath, ["-e",
          `process.stdout.write(${JSON.stringify(output)}); process.exit(${status});`,
        ], options);
      } finally {
        onExit(record);
      }
    },
    resolveSystemCliDescriptor: () => ({ path: process.execPath }),
    readSessionStateHandoff: () => ({ path: "owned-checkpoint", record }),
    writeJsonAtomic: (_path, value) => { record = structuredClone(value); },
    writeSessionStateHandoff: () => ({
      ok: true, path: "owned-checkpoint", record: { ...record, launchRequested: false },
    }),
    resolveHerdrCwd: cwd => cwd,
    readNativeGoal: async () => ({ state: null }),
    isHerdrPane: () => herdr,
    launchHerdrSuccessor: () => assert.fail("No Herdr launch expected"),
  });
  vm.runInContext(`${runCliSource}\n${source}
    globalThis.request = requestNativeCutover;
    globalThis.launch = freezeAndLaunchNative;`, context);
  const session = { sessionId: "source", rpc: {
    mode: {
      get: async () => "interactive",
      set: async value => { pauses.push(value); return {}; },
    },
    permissions: { getMode: async () => ({ mode: permissionMode }) },
    model: { getCurrent: async () => ({ modelId: "owned-model" }) },
    agent: { getCurrent: async () => ({ agent: null }) },
  } };
  if (plain) {
    Object.assign(context, {
      session, state: { sessionId: "source", pendingHandoff: pending },
      nativeStartup: Promise.resolve(), nativeStartupError: null, nativeCutoverPath: null,
      ensureState: () => {}, currentHandoffCwd: () => ({ cwd: process.cwd() }),
    });
    const extension = readFileSync(new URL(
      "../extensions/context-handoff/extension.mjs", import.meta.url,
    ), "utf8");
    for (const [name, key] of [["continue_handoff", "publicContinue"], ["retry_handoff_cutover", "publicRetry"]]) {
      const start = extension.indexOf("handler: async", extension.indexOf(`name: "${name}"`));
      const end = extension.indexOf("\n      },\n    },", start);
      assert.ok(start >= 0 && end > start);
      vm.runInContext(`globalThis.${key} = (${extension.slice(start + "handler: ".length, end)}\n});`, context);
    }
  }
  return {
    record: () => record, calls, pauses,
    request: () => context.request(session, record.seed),
    launch: () => context.launch(session, "owned-checkpoint"),
    continue: () => context.publicContinue({ seed: record.seed }, {}),
    retry: () => context.publicRetry({}, {}),
    setExit: (nextStatus, nextOutput) => { status = nextStatus; output = nextOutput; },
  };
}

test("rc4 retained receiver publishes the receipt and retry never spawns again", async () => {
  const receipt = {
    ok: false, new_pane: "%5", prompt_received: true,
    candidate_status: "session-association-timeout",
    error: "successor did not create a token-associated Copilot session",
  };
  const f = fixture({
    status: 4, output: JSON.stringify(receipt),
    onExit: record => { record.nativeGoal.receiverObservation = "preserve concurrent write"; },
  });
  assert.deepEqual(await f.launch(), receipt);
  assert.deepEqual(f.record().nativeGoal.launch, receipt);
  assert.equal(f.record().nativeGoal.launchRequested, true);
  assert.equal(f.record().nativeGoal.receiverObservation, "preserve concurrent write");
  assert.deepEqual((await f.request()).launch, receipt);
  assert.deepEqual(await f.launch(), receipt);
  assert.equal(f.calls.length, 1);
});

test("rc3 prelaunch rejection clears the request and permits an explicit retry", async () => {
  const f = fixture({
    status: 3, output: JSON.stringify({ ok: false, error: "no mux session wt-owned; not under mux" }),
  });
  await assert.rejects(f.launch(), /no mux session/);
  assert.equal(f.record().nativeGoal.launchRequested, false);
  assert.equal(f.record().nativeGoal.launch, undefined);
  assert.equal((await f.request()).pending, true);
  await assert.rejects(f.launch(), /no mux session/);
  assert.equal(f.calls.length, 2);
});

test("unknown or malformed child outcomes preserve the request and forbid blind retry", async () => {
  for (const [status, output] of [
    [4, '{"ok":false,"new_pane":null,"error":"mux timeout"}'],
    [3, "not JSON"],
    [4, "{}"],
    [7, '{"ok":false,"error":"unknown transport outcome"}'],
  ]) {
    const f = fixture({ status, output });
    await assert.rejects(f.launch());
    assert.equal(f.record().nativeGoal.launchRequested, true);
    assert.equal(f.record().nativeGoal.launch, undefined);
    await assert.rejects(f.request(), /unresolved/);
    await assert.rejects(f.launch(), /unresolved/);
    assert.equal(f.calls.length, 1);
  }
});

test("native manual/assisted requests on either host reject before pause or arming", async () => {
  for (const herdr of [false, true]) {
    for (const permissionMode of ["manual", "assisted"]) {
      const f = fixture({ permissionMode, herdr });
      const before = structuredClone(f.record());
      await assert.rejects(f.request(), /cannot preserve/);
      assert.deepEqual(f.record(), before);
      assert.equal(f.pauses.length, 0);
      assert.equal(f.calls.length, 0);
      await assert.rejects(f.launch(), /cannot preserve/);
      assert.deepEqual(f.record(), before);
      assert.equal(f.calls.length, 0);
      // A receipt written by an older, permissive source is not acceptance.
      f.record().nativeGoal.launch = { ok: true, new_pane: "%old" };
      await assert.rejects(f.request(), /cannot preserve/);
      await assert.rejects(f.launch(), /cannot preserve/);
      assert.equal(f.pauses.length, 0);
      assert.equal(f.calls.length, 0);
    }
  }
});

test("allow-all native requests still pause, launch once and reuse the receipt", async () => {
  const f = fixture();
  assert.equal((await f.request()).pending, true);
  assert.equal(f.pauses.length, 1);
  assert.equal(f.record().nativeGoal.cutoverRequested, true);
  assert.equal((await f.launch()).new_pane, "%5");
  assert.equal((await f.request()).launch.new_pane, "%5");
  assert.equal(f.calls.length, 1);
});

test("plain public continue and retry recover a real rc3 pre-creation CLI exit", async () => {
  const f = fixture({ plain: true, status: 3, output: '{"ok":false,"error":"no mux session"}' });
  await f.continue();
  await assert.rejects(f.launch(), /no mux session/);
  assert.equal(f.record().launchRequested, false);
  await f.retry();
  f.setExit(0, '{"ok":true,"new_pane":"%5"}');
  await f.launch();
  await f.retry();
  assert.equal(f.calls.length, 2);
  assert.equal(f.record().launch.new_pane, "%5");
});

test("plain retained rc4 publishes receiver updates and never respawns on retry", async () => {
  const receipt = { ok: false, new_pane: "%5", error: "receiver pending" };
  const f = fixture({
    plain: true, status: 4, output: JSON.stringify(receipt),
    onExit: record => { record.receiverObservation = "keep concurrent receiver update"; },
  });
  await f.continue();
  assert.deepEqual(await f.launch(), receipt);
  assert.deepEqual(f.record().launch, receipt);
  assert.equal(f.record().receiverObservation, "keep concurrent receiver update");
  await f.retry();
  await f.launch();
  assert.equal(f.calls.length, 1);
});

test("plain malformed and unknown nonzero CLI outcomes stay unresolved", async () => {
  for (const [status, output] of [
    [3, "not JSON"], [4, '{"ok":false,"error":"unknown pane creation"}'],
    [4, "{}"], [7, '{"ok":false,"error":"unknown stage"}'],
  ]) {
    const f = fixture({ plain: true, status, output });
    await f.continue();
    await assert.rejects(f.launch());
    assert.equal(f.record().launchRequested, true);
    await assert.rejects(f.retry(), /unresolved/);
    assert.equal(f.calls.length, 1);
  }
});
