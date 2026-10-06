---
name: consume-handoff
description: >
  Copilot /consume-handoff and tool consume_handoff. Load this worktree's
  pending handoff into THIS session and continue from the stored brief.
argument-hint: "[task:<id>|file:<id>|HANDOFF_SEED]"
user-invocable: true
---

# consume_handoff / /consume-handoff

```bash
H="$HOME/.grok/plugins/context-handoff/scripts/grok-handoff.sh"
```

If the user passed `task:<id>`, `file:<id>`, or a seed Recovery locator, consume
that. Otherwise `bash "$H" facts` and prefer this worktree's newest pending
agent-dispatch task, else the newest unconsumed file. No global search.

```bash
bash "$H" consume --locator "task:<id>"
bash "$H" consume --locator "file:<id>"
```

On success, follow the payload brief and `native-goal-continuity`. Consuming is
setup, not completion.

If already claimed, state `claimedBySession`. Do not invent another objective.
Offer to file a bug only if the user says yes.
