import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// Install $home/.local/bin/herdr whose `pane get` reports only livePaneId.
export function installFakeHerdr(home, livePaneId) {
  const bin = join(home, ".local", "bin");
  mkdirSync(bin, { recursive: true });
  const herdr = join(bin, "herdr");
  writeFileSync(herdr, `#!/bin/sh
if [ "$1 $2 $3" = "pane get ${livePaneId}" ]; then
  echo '{"result":{"pane":{"pane_id":"${livePaneId}"}}}'
  exit 0
fi
echo '{"error":{"code":"pane_not_found"}}'
exit 1
`);
  chmodSync(herdr, 0o755);
  return herdr;
}
