---
name: handoff-continue
description: >
  Save a handoff for this session and launch a live successor. Explicit
  operator authorization — do not ask first. Claude launches --kind claude;
  Grok uses grok-pane.
argument-hint: "[title]"
user-invocable: true
---

# /handoff-continue

1. Collect facts (`generate_handoff_prompt` / `bash grok-handoff.sh facts`).
2. Compose markdown per `skills/context-handoff` + `references/handoff-template.md`.
3. Save (`save_handoff_prompt` / `bash grok-handoff.sh save --title ... --prompt-file ...`).
4. Continue with the exact `HANDOFF_SEED` / `HANDOFF_TOKEN`:
   - Claude: `bash grok-handoff.sh continue --kind claude --handoff-token <id>`
   - Grok: `bash grok-handoff.sh continue --handoff-token <id>`
5. End the turn. Do not claim auto-load on restart.
