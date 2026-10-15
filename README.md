# tlvc - version control for video timelines

Problem 10 from Cardboard's "Hard problems" doc: code has git, video has `final_v3_actual (1).mp4`. What does a diff of a timeline even look like, and how do you merge two editors' work without anyone touching git?

`tlvc` is a small, working answer to the backend half of that question: a timeline data model, a semantic diff, a three-way merge with structured conflicts, and a branch/commit/merge CLI. Python 3.10+, standard library only.

## Try it

```sh
sh examples/demo.sh          # two editors branch, one clean merge, one conflict, resolve, commit
python3 -m unittest discover -s tests
```

Demo output (abridged):

```
--- diff main vs colorist
intro.asset: 'intro_v2.mp4' -> 'intro_graded.mp4'
main.fx.grade: None -> {'lut': 'warm'}
music.dur: 300 -> 690
--- merge
1 conflict(s); working file holds 'ours' for each:
[0] intro.asset: base='intro.mp4' ours='intro_v2.mp4' theirs='intro_graded.mp4'
```

The music trim and the color grade merged on their own. Only the clip both editors replaced is surfaced.

## How it works

A timeline is JSON with integer frame times and clips keyed by a stable id (`examples/base.json`). Because identity is the clip id, not a line number:

- **Diff** is semantic: `add`, `remove`, or `set clip.field old -> new` (including per-effect `fx.<name>`). A move or trim is one change.
- **Merge** is three-way, per clip and per field. Both sides agree or only one changed: automatic. Different fields of the same clip: automatic. Same field changed differently, remove vs edit, or same id added twice: conflict.
- **Overlap conflicts** catch what text merges cannot: two editors each place a different clip into the same gap on a track. No single field clashed, but the result is invalid, so it is reported and you fix it by moving a clip, then `merge --continue`.
- **Conflicts are data**, listed with base/ours/theirs values and resolved with `tlvc resolve <n> ours|theirs`.
- **Storage** is content-addressed snapshots in `.tlvc/`; merge base is the nearest common ancestor.

```
tlvc init | commit -m MSG | log | status | branch [name] | checkout NAME
tlvc diff A B | merge BRANCH | resolve N ours|theirs | merge --continue
```

## What this does and does not prove

Covered by 14 tests: clean and conflicting merges, symmetry of clean merges, remove-vs-edit, add-add, overlap detection, fast-forward, and the full CLI conflict/resolve/continue flow.

Not covered: media. Clips reference assets by name; nothing here reads video, syncs large files, or renders. Merge base uses the nearest common ancestor, not the full criss-cross handling git does. Only one conflict policy (ours/theirs per field). Overlap is the only cross-clip invariant checked; linked audio/video pairs, transitions and nested sequences are not modeled. It is a core to build on, not a finished product.

AI-assisted prototype; tests and demo commands are reproducible above.
