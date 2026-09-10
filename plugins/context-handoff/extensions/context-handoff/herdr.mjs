// Adapt native handoff to the fork's existing Herdr identity and launch contract.
import {
  isHerdrPane, resolveHandoffCwd, runHerdrHandoffCutover,
  retireHerdrPredecessorAfterConsume,
} from "./handoff-core.mjs";

export { isHerdrPane };

export function resolveHerdrCwd(cwd, execute) {
  const result = resolveHandoffCwd(cwd, { execute });
  if (!result.cwd) throw new Error(result.error);
  return result.cwd;
}

export function launchHerdrSuccessor(cwd, seed, execute, permissionMode, native = null) {
  if (permissionMode !== "allow-all") {
    throw new Error(`Herdr cannot preserve ${permissionMode}; no pane was created.`);
  }
  return runHerdrHandoffCutover(cwd, seed, process.env.COPILOT_AGENT_SESSION_ID, {
    execute, permissionMode, native, throwLaunchErrors: true,
  });
}

export function retireHerdrPredecessor(metadata, successorSessionId, execute) {
  const result = retireHerdrPredecessorAfterConsume({
    consumed: true, metadata, successorSessionId,
  }, { execute });
  if (!result.retired) {
    throw new Error(`Herdr predecessor preserved: ${result.error || result.status}`);
  }
  return result;
}
