import { existsSync, readFileSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join, resolve } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { workerLifecycle } from "./herdr.mjs";
import { runCli } from "./handoff-core.mjs";

function cliBasename(cli) {
  return String(cli || "").split(/[/\\]/).pop().replace(/\.exe$/i, "");
}

export function isGrokCli(cli) {
  return cliBasename(cli) === "grok";
}

function grokReceiverExists(home, sessionId) {
  const root = join(home, "sessions");
  if (!existsSync(root) || !sessionId) return false;
  if (existsSync(join(root, sessionId, "events.jsonl"))
    || existsSync(join(root, sessionId, "chat_history.jsonl"))) {
    return true;
  }
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    if (existsSync(join(root, entry.name, sessionId, "events.jsonl"))
      || existsSync(join(root, entry.name, sessionId, "chat_history.jsonl"))) {
      return true;
    }
  }
  return false;
}

export function nativeLaunchArguments(record, phase, args = [], { receiverExists = false, grok = false } = {}) {
  const goal = record.nativeGoal;
  if (!goal?.successorSessionId || !record.seed) {
    throw new Error("Native handoff launch requires a frozen successor identity and seed.");
  }
  const allowedModes = grok ? ["allow-all", "always-approve"] : ["allow-all"];
  if (!allowedModes.includes(goal.permissionMode)) {
    throw new Error(`Native handoff cannot preserve ${goal.permissionMode}; no CLI was launched.`);
  }
  const launchArgs = [];
  const profileOptions = grok
    ? new Set(["--model", "--effort", "--reasoning-effort", "--agent"])
    : new Set(["--model", "--effort", "--context", "--agent"]);
  for (let index = 0; index < args.length; index++) {
    if (args[index] === "--session-id") {
      if (args[++index] !== goal.successorSessionId) {
        throw new Error("Launcher session identity disagrees with the native handoff.");
      }
    } else if (goal.profile && profileOptions.has(args[index].split("=")[0])) {
      if (!args[index].includes("=")) index++;
    } else {
      launchArgs.push(args[index]);
    }
  }
  if (goal.profile) {
    const { model, agentId } = goal.profile;
    if (!model.modelId) throw new Error("Source model identity is unavailable; source preserved.");
    launchArgs.push("--model", model.modelId);
    if (model.reasoningEffort) launchArgs.push("--effort", model.reasoningEffort);
    if (!grok && model.contextTier) launchArgs.push("--context", model.contextTier);
    if (agentId) launchArgs.push("--agent", agentId);
  }
  if (grok) {
    if (phase === "prepare" && !receiverExists) {
      return [...launchArgs, "--session-id", goal.successorSessionId, "--always-approve"];
    }
    return [...launchArgs, "--resume", goal.successorSessionId];
  }
  if (phase === "prepare" && !receiverExists) {
    return [
      ...launchArgs, "--session-id", goal.successorSessionId,
      "--name", `Handoff ${record.handoffId}`.slice(0, 100),
      "--mode", "interactive",
    ];
  }
  return [
    ...launchArgs, "--resume", goal.successorSessionId,
    "--mode", "interactive",
  ];
}

export function runNativeSuccessor({ checkpoint, cli, args = [], spawn = spawnSync, lifecycleCheck = workerLifecycle }) {
  const load = () => JSON.parse(readFileSync(checkpoint, "utf8"));
  let record = load();
  const grok = isGrokCli(cli) || Boolean(record.nativeGoal?.profile?.grokHome);
  const run = phase => {
    // First-trust interruption can leave the named empty CLI saved before
    // bootstrap writes the objective. Continue that exact receiver, not a
    // second creation of its UUID.
    const home = grok
      ? (record.nativeGoal.profile?.grokHome || process.env.GROK_HOME || join(homedir(), ".grok"))
      : (record.nativeGoal.profile?.copilotHome
        || process.env.COPILOT_HOME || join(homedir(), ".copilot"));
    const receiverExists = grok
      ? grokReceiverExists(home, record.nativeGoal.successorSessionId)
      : existsSync(join(home, "session-state", record.nativeGoal.successorSessionId, "events.jsonl"));
    const lifecycle = record.nativeGoal.workerLifecycle;
    if (lifecycle && !grok) {
      lifecycleCheck(record, checkpoint, "handoff-check", record.nativeGoal.successorSessionId, runCli);
    }
    const selectors = (!grok && lifecycle) ? [
      "--worker-selectors", lifecycle.config_home, lifecycle.xdg_home,
      lifecycle.mode, String(lifecycle.depth),
    ] : [];
    const result = spawn(cli, [
      ...selectors, ...nativeLaunchArguments(record, phase, args, { receiverExists, grok }),
    ], {
      cwd: record.nativeGoal.cwd,
      stdio: "inherit",
      env: {
        ...process.env,
        ...(grok
          ? { GROK_HOME: record.nativeGoal.profile?.grokHome || process.env.GROK_HOME || home, GROK_PANE: "1" }
          : (record.nativeGoal.profile?.copilotHome
            ? { COPILOT_HOME: record.nativeGoal.profile.copilotHome } : {})),
        CONTEXT_HANDOFF_NATIVE_CHECKPOINT: checkpoint,
        CONTEXT_HANDOFF_NATIVE_PHASE: phase,
      },
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      throw new Error(`Native handoff ${phase} CLI exited ${result.status ?? result.signal}; predecessor preserved.`);
    }
  };
  if (record.nativeGoal.phase === "frozen") {
    run("prepare");
    record = load();
  }
  if (record.nativeGoal.workerLifecycle && record.nativeGoal.admissionComplete) {
    run("resume");
    return;
  }
  if (!["prepared", "hydrated"].includes(record.nativeGoal.phase)
    || record.nativeGoal.admissionComplete) {
    throw new Error("Native successor is not awaiting cold resume; do not launch another receiver.");
  }
  run("resume");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [checkpointFlag, checkpoint, cliFlag, cli, separator, ...args] = process.argv.slice(2);
  if (checkpointFlag !== "--checkpoint" || cliFlag !== "--cli" || separator !== "--") {
    throw new Error("Usage: native-launch.mjs --checkpoint PATH --cli COPILOT -- [CLI options]");
  }
  runNativeSuccessor({ checkpoint, cli, args });
}
