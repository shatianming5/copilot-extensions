import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import vm from "node:vm";
import { acknowledgeNativeGoal, activateNativeGoal } from "../extensions/context-handoff/native-goal.mjs";

const extension = readFileSync(new URL("../extensions/context-handoff/extension.mjs", import.meta.url), "utf8");
const runtime = readFileSync(new URL("../extensions/context-handoff/native-runtime.mjs", import.meta.url), "utf8")
  .replace(/^import[\s\S]*?from "[^"]+";\n/gm, "").replaceAll("export ", "");

function handler(name) {
  const start = extension.indexOf("handler: async", extension.indexOf(`name: "${name}"`));
  const end = extension.indexOf("\n      },\n    },", start);
  assert.ok(start >= 0 && end > start);
  return extension.slice(start + "handler: ".length, end) + "\n}";
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture(storage, failStartup) {
  const workspace = deferred();
  const activation = deferred();
  const model = { modelId: "owned-model", reasoningEffort: "high", contextTier: "default" };
  const frozen = {
    id: 1, objective: "Owned native objective", status: "active",
    turnCount: 2, creditCountNanoAiu: "125000001",
    creditLimit: { credits: 0.375, creditsUsedNanoAiu: "125000001" },
  };
  let native = { ...frozen, status: "paused", pauseReason: "resumed_session" };
  let record = {
    kind: "context-handoff-session-request", sessionId: "source", handoffId: "token",
    storage, handoffPath: "baton", taskId: storage === "agent-dispatch" ? "token" : null,
    promptText: "Owned checkpoint", consumed: false,
    nativeGoal: {
      version: 1, phase: "prepared", successorSessionId: "target", state: frozen,
      remainingCredits: "0.249999999", intent: "running", cwd: "/owned",
      permissionMode: "allow-all", profile: { model, agentId: null },
    },
  };
  const counts = { consume: 0, activation: 0, messages: 0 };
  const events = [];
  const listeners = new Map();
  const logs = [];
  let workspaceEntered = false;
  const emit = type => { for (const listener of listeners.get(type) || []) listener({ type, data: {} }); };
  const session = {
    sessionId: "target",
    on: (type, listener) => {
      listeners.set(type, [...(listeners.get(type) || []), listener]);
    },
    log: async message => { logs.push(message); },
    getEvents: async () => structuredClone(events),
    send: async ({ prompt }) => {
      counts.messages++;
      const id = `message-${counts.messages}`;
      events.push({ id, type: "user.message", data: { content: prompt, messageId: id } });
      emit("user.message");
      return id;
    },
    rpc: {
      model: { getCurrent: async () => model },
      agent: { getCurrent: async () => ({ agent: null }) },
      permissions: { getMode: async () => ({ mode: "allow-all" }) },
      workspaces: { createFile: async () => {
        workspaceEntered = true;
        await workspace.promise;
        if (failStartup) throw new Error("Owned workspace failure");
      } },
      commands: { invoke: async () => {
        counts.activation++;
        await activation.promise;
        native = { ...native, status: "active", pauseReason: undefined };
        return { kind: "agent-prompt", mode: "autopilot", prompt: "Continue owned goal." };
      } },
    },
  };
  const metadata = { nativeGoalCheckpoint: "checkpoint" };
  const consume = () => {
    counts.consume++;
    record.nativeGoal.consumedBySession = "target";
    return { ok: true, id: "token", metadata, payload: record.promptText };
  };
  const context = vm.createContext({
    process: { env: {
      CONTEXT_HANDOFF_NATIVE_CHECKPOINT: "checkpoint", CONTEXT_HANDOFF_NATIVE_PHASE: "resume",
    } },
    session, state: { sessionId: "target" }, basename,
    readFileSync: () => JSON.stringify(record),
    writeJsonAtomic: (_path, value) => { record = structuredClone(value); },
    readNativeGoal: async () => ({ state: structuredClone(native) }),
    acknowledgeNativeGoal, activateNativeGoal,
    consumeFileHandoff: consume, consumeDispatchHandoffTask: consume,
    ensureState: () => {}, currentHandoffCwd: () => ({ cwd: "/owned" }),
    isHerdrPane: () => false, agentDispatchAvailable: () => storage === "agent-dispatch",
    agentWorktreesGet: () => "/owned", findHandoffTask: () => ({ id: "token" }),
    findHandoffFile: () => ({ path: "baton", record: { id: "token" } }),
    recoverPendingHandoff: () => null, readSessionStateHandoff: () => null,
    runCli: () => assert.fail("No host operation is required"),
  });
  const startupStart = extension.indexOf("nativeStartup = bootstrapNativeHandoff(session)");
  const startupEnd = extension.indexOf("if (handoffConfig.warning)", startupStart);
  const observerStart = extension.indexOf("let pendingNudge = null;");
  const observerEnd = extension.indexOf("// --- Real-time context utilization", observerStart);
  vm.runInContext(`
    ${runtime}
    let nativeStartup, nativeStartupError = null, nativeReceiptPath = null, nativeCutoverPath = null;
    ${extension.slice(startupStart, startupEnd)}
    ${extension.slice(observerStart, observerEnd)}
    globalThis.ready = () => nativeStartup;
    globalThis.consume = (${handler("consume_handoff")});
    globalThis.resume = (${handler("resume-handoff")});
  `, context);
  return {
    context, counts, logs, emit, workspace, activation,
    entered: () => workspaceEntered, record: () => record,
  };
}

for (const route of ["tool-file", "tool-path", "tool-task", "resume-file", "resume-task"]) {
  for (const failStartup of [false, true]) {
    test(`${route} waits for actual bootstrap before native admission${failStartup ? " or startup failure" : ""}`, async () => {
      const f = fixture(route.endsWith("task") ? "agent-dispatch" : "file", failStartup);
      const invoke = () => route.startsWith("resume") ? f.context.resume({}) : f.context.consume(
        route === "tool-task" ? { task_id: "token" }
          : route === "tool-path" ? { path: "baton" } : { handoff_id: "token" }, {},
      );
      await tick();
      assert.equal(f.entered(), true);
      assert.equal(f.record().nativeGoal.phase, "hydrated");
      const publicCall = invoke().then(value => ({ value }), error => ({ error }));
      await tick();
      const consumedDuringBootstrap = f.counts.consume;
      f.emit("session.idle");
      f.emit("user.message");
      f.workspace.resolve();
      await tick();
      f.activation.resolve();
      await f.context.ready();
      const result = await publicCall;
      assert.equal(consumedDuringBootstrap, 0, `public consumer ran while workspace RPC was pending: ${JSON.stringify(f.counts)}`);
      if (failStartup) {
        assert.ok(result.error?.message.includes("Owned workspace failure")
          || (result.value?.resultType === "error" && result.value.textResultForLlm.includes("Owned workspace failure")));
        assert.deepEqual(f.counts, { consume: 0, activation: 0, messages: 0 });
      } else {
        assert.equal(result.error, undefined);
        await Promise.all([invoke(), invoke()]);
        f.emit("session.idle");
        f.emit("user.message");
        await tick();
        assert.equal(f.counts.activation, 1);
        assert.equal(f.counts.messages, 1);
        assert.equal(f.record().nativeGoal.admissionComplete, true);
      }
    });
  }
}
