---
name: generate-handoff-prompt
description: >
  Copilot tool generate_handoff_prompt. Collect session facts for a
  continuation brief. Use when the model would call generate_handoff_prompt
  or the user asks to generate a handoff.
user-invocable: true
---

# generate_handoff_prompt

Copilot's in-session extension is not loaded in Grok. Collect the same facts
with the payload CLI, git, and live context.

```bash
bash "$HOME/.grok/plugins/context-handoff/scripts/grok-handoff.sh" facts
git status
git diff --stat
```

Return: session metadata, modified files, git status, and an instruction to
compose either the effort-backed or standalone template from
`skills/context-handoff/references/handoff-template.md`. Preserve the parent
completion gate. Do not save or launch in this step.
