import argparse, json, sys
from .store import Repo
from .model import diff, describe, overlaps, validate
from .merge import merge3, apply_resolution


def _show_conflict(i, c):
    k = c["kind"]
    if k == "field":
        return f"[{i}] {c['clip']}.{c['path']}: base={c['base']!r} ours={c['ours']!r} theirs={c['theirs']!r}"
    if k == "overlap":
        return f"[{i}] overlap on track {c['track']}: {c['a']} and {c['b']} (move one, then `tlvc merge --continue`)"
    if k == "remove-edit":
        return f"[{i}] {c['clip']}: removed by {c['removed_by']} but edited by the other side"
    return f"[{i}] {c['clip']}: added on both sides with different content"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tlvc", description="Version control for video timelines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("--file", default="timeline.json")
    s = sub.add_parser("commit"); s.add_argument("-m", required=True)
    sub.add_parser("log"); sub.add_parser("status")
    s = sub.add_parser("branch"); s.add_argument("name", nargs="?")
    s = sub.add_parser("checkout"); s.add_argument("name")
    s = sub.add_parser("diff"); s.add_argument("a"); s.add_argument("b")
    s = sub.add_parser("merge"); s.add_argument("branch", nargs="?"); s.add_argument("--continue", dest="cont", action="store_true")
    s = sub.add_parser("resolve"); s.add_argument("index", type=int); s.add_argument("side", choices=["ours", "theirs"])
    a = ap.parse_args(argv)
    r = Repo(".")

    def dirty():
        return diff(r.get(r.head())["timeline"], r.read_working())
    try:
        if a.cmd == "init":
            r.init(a.file); print("initialised")
        elif a.cmd == "commit":
            if r.load_merge():
                print("merge in progress; use `tlvc merge --continue`"); return 1
            print(r.commit(a.m))
        elif a.cmd == "log":
            for h, m in r.log(): print(h, m)
        elif a.cmd == "branch":
            if a.name: r.create_branch(a.name)
            else:
                for b in r.branches(): print(("* " if b == r.branch() else "  ") + b)
        elif a.cmd == "checkout":
            if r.load_merge(): print("merge in progress"); return 1
            if dirty(): print("uncommitted changes; commit first"); return 1
            r.checkout(a.name)
        elif a.cmd == "status":
            head = r.get(r.head())["timeline"]
            ch = diff(head, r.read_working())
            print(f"on {r.branch()}, {len(ch)} uncommitted change(s)")
            for c in ch: print("  " + describe(c))
            m = r.load_merge()
            if m: print("merge in progress, unresolved:", len(m["conflicts"]))
        elif a.cmd == "diff":
            for c in diff(r.get(r.resolve_ref(a.a))["timeline"], r.get(r.resolve_ref(a.b))["timeline"]):
                print(describe(c))
        elif a.cmd == "resolve":
            m = r.load_merge()
            if not m: print("no merge in progress"); return 1
            apply_resolution(m["merged"], m["conflicts"][a.index], a.side)
            m["conflicts"].pop(a.index); r.save_merge(m); r.write_working(m["merged"])
            print(f"{len(m['conflicts'])} conflict(s) left")
        elif a.cmd == "merge":
            if a.cont:
                m = r.load_merge()
                if not m: print("no merge in progress"); return 1
                tl = r.read_working()  # user may have moved clips to fix overlaps
                left = [c for c in m["conflicts"] if c["kind"] != "overlap"]
                left += [dict(c, kind="overlap") for c in overlaps(tl)]
                if left:
                    for i, c in enumerate(left): print(_show_conflict(i, c))
                    return 1
                h = r.commit(f"Merge {m['theirs_name']}", parents=[m["ours"], m["theirs"]], timeline=tl)
                r.clear_merge(); print("merged", h); return 0
            if r.load_merge(): print("merge already in progress"); return 1
            if dirty(): print("uncommitted changes; commit first"); return 1
            ours, theirs = r.head(), r.resolve_ref(a.branch)
            base = r.merge_base(ours, theirs)
            if base == theirs: print("already up to date"); return 0
            if base == ours:
                r._w("heads/" + r.branch(), theirs); r.write_working(r.get(theirs)["timeline"])
                print("fast-forward", theirs); return 0
            merged, conf = merge3(r.get(base)["timeline"], r.get(ours)["timeline"], r.get(theirs)["timeline"])
            if not conf:
                h = r.commit(f"Merge {a.branch}", parents=[ours, theirs], timeline=merged)
                r.write_working(merged); print("merged", h); return 0
            r.save_merge({"ours": ours, "theirs": theirs, "theirs_name": a.branch, "merged": merged, "conflicts": conf})
            r.write_working(merged)
            print(f"{len(conf)} conflict(s); working file holds 'ours' for each:")
            for i, c in enumerate(conf): print(_show_conflict(i, c))
            return 1
    except (KeyError, RuntimeError, ValueError, OSError) as e:
        print("error:", e, file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
