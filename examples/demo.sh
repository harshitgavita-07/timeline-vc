#!/bin/sh
# Two editors branch from one cut; one change merges cleanly, one conflicts.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd); D=$(mktemp -d); cd "$D"
tlvc() { PYTHONPATH="$ROOT" python3 -m tlvc "$@"; }
cp "$ROOT/examples/base.json" timeline.json
tlvc init; tlvc commit -m "first cut"; tlvc branch colorist
python3 - <<'PY'
import json; t=json.load(open("timeline.json"))
t["clips"]["intro"]["asset"]="intro_v2.mp4"; t["clips"]["music"]["start"]=0; t["clips"]["music"]["dur"]=300
json.dump(t,open("timeline.json","w"))
PY
tlvc commit -m "editor: swap intro, trim music"
tlvc checkout colorist
python3 - <<'PY'
import json; t=json.load(open("timeline.json"))
t["clips"]["intro"]["asset"]="intro_graded.mp4"; t["clips"]["main"]["effects"]["grade"]={"lut":"warm"}
json.dump(t,open("timeline.json","w"))
PY
tlvc commit -m "colorist: grade main, regrade intro"
tlvc checkout main
echo "--- diff main vs colorist"; tlvc diff main colorist
echo "--- merge"; tlvc merge colorist || true
echo "--- resolve: take colorist's intro"; tlvc resolve 0 theirs; tlvc merge --continue
echo "--- log"; tlvc log
