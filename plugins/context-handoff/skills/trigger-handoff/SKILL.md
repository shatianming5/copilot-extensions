---
name: trigger-handoff
description: >
  Copilot tool trigger_handoff. Signal pickup for a saved baton without
  process management. Not for native-goal batons (those use continue_handoff).
argument-hint: "[--handoff-token id | --prompt-file f]"
user-invocable: true
---

# trigger_handoff

Signal-only pickup. Does not spawn, retire, or inspect panes.

```bash
# reuse saved token
bash "$HOME/.grok/plugins/context-handoff/scripts/grok-handoff.sh" trigger \
  --handoff-token "<id>"
# or store+signal
bash "$HOME/.grok/plugins/context-handoff/scripts/grok-handoff.sh" trigger \
  --title "<t>" --prompt-file "<file>"
```

If facts/save indicated a native goal, stop and use `continue_handoff` with
the exact seed instead. Always print the final seed. Never claim auto-pickup.
