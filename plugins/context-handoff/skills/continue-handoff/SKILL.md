---
name: continue-handoff
description: >
  Freeze the saved native-goal baton and launch a successor. On Claude Code,
  launch a Claude successor (--kind claude). On Grok, launch grok-pane.
  Pass the exact HANDOFF_SEED from save_handoff_prompt.
argument-hint: "<HANDOFF_SEED>"
user-invocable: true
---

# continue_handoff

Requires the exact `HANDOFF_SEED` from `save_handoff_prompt`. Do not create a
second baton.

```bash
H="$HOME/.grok/plugins/context-handoff/scripts/grok-handoff.sh"
```

1. If the seed is missing, stop. Recover the existing baton; do not save again.
2. Extract `HANDOFF_TOKEN` from the seed (the `file:<id>` / token id). Do not
   invent a new token.
3. Launch the successor for **this host**:

   **Claude Code**

   ```bash
   bash "$H" continue --kind claude --handoff-token "<HANDOFF_TOKEN>"
   ```

   Inside Herdr (`HERDR_ENV=1`) this splits a sibling pane and runs
   `herdr agent start --kind claude`, then submits `/consume-handoff file:<id>`.
   Never `grok-pane`, `copilot-pane`, or `--kind grok` / `--kind copilot`.

   Outside Herdr the script prints the consume locator. Spawn a Claude teammate
   (Agent tool) with that prompt, or open a new Claude Code session in the same
   cwd and run `/consume-handoff file:<id>`.

   **Grok**

   After `save`, from the predecessor Herdr pane:

   ```bash
   bash "$H" continue --handoff-token "<HANDOFF_TOKEN>"
   ```

   That launches `grok-pane` and submits `/consume-handoff file:<id>`. Do not
   pass `--native-handoff` unless the checkpoint contains
   `nativeGoal.successorSessionId`. Outside Herdr, launch `spawn_subagent` with
   the stored brief.

4. Child prompt: consume this seed, restore `/goal` with remaining budget
   (`native-goal-continuity`), start the Successor Work Roster. A paused goal
   does not resume GPU work.
5. Use `isolation: worktree` when edits must stay isolated.
6. Paused / exhausted / completed / no-goal: spawn with no automatic business
   `/goal` message. Running goal continues once.
7. End this turn. Do not replay if a successor was already launched.

Retry the same identity with `retry_handoff_cutover`, not a new save.
