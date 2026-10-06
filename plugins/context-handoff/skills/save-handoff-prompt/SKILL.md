---
name: save-handoff-prompt
description: >
  Copilot tool save_handoff_prompt. Store composed handoff markdown and return
  HANDOFF_SEED / HANDOFF_TOKEN. Does not launch a successor.
argument-hint: "[title]"
user-invocable: true
---

# save_handoff_prompt

Write the composed markdown to a temp file, then:

```bash
bash "$HOME/.grok/plugins/context-handoff/scripts/grok-handoff.sh" save \
  --title "<short topic>" --prompt-file "<file>"
```

Print `HANDOFF_SEED` and `HANDOFF_TOKEN`. Save is not launch.

- Context pressure + work remaining → call `trigger_handoff` or
  `/handoff-continue` next, do not ask.
- Native goal in the baton → `continue_handoff` / `/handoff-continue`, not
  signal-only `trigger_handoff`.
- Turn-end follow-ups → ask before trigger, unless already authorized.
