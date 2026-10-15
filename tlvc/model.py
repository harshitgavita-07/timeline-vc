"""Timeline model and semantic diff.

A timeline is plain JSON:
  {"fps": 30, "clips": {"<stable id>": {"track": 0, "start": 0, "dur": 90,
                                         "asset": "a.mp4", "in": 0,
                                         "effects": {"blur": {"r": 4}}}}}
All times are integer frames. Clips are keyed by a stable id, so a move or trim
is one change to one clip instead of a text diff of a line.
"""
import copy

FIELDS = ("track", "start", "dur", "asset", "in")


def validate(tl):
    if not isinstance(tl, dict) or not isinstance(tl.get("clips"), dict):
        raise ValueError("timeline must be an object with a 'clips' object")
    for cid, c in tl["clips"].items():
        for f in FIELDS:
            if f not in c:
                raise ValueError(f"clip {cid} missing field {f!r}")
        for f in ("track", "start", "dur", "in"):
            if not isinstance(c[f], int) or isinstance(c[f], bool):
                raise ValueError(f"clip {cid} field {f!r} must be an integer (frames)")
        if c["dur"] <= 0:
            raise ValueError(f"clip {cid} has non-positive duration")
        c.setdefault("effects", {})
    return tl


def flatten(clip):
    """Clip -> {path: value}; effects become 'fx.<name>' entries."""
    out = {f: clip[f] for f in FIELDS}
    for name, params in clip.get("effects", {}).items():
        out["fx." + name] = params
    return out


def unflatten(flat):
    clip = {f: flat[f] for f in FIELDS}
    clip["effects"] = {k[3:]: v for k, v in sorted(flat.items()) if k.startswith("fx.")}
    return clip


def diff(base, new):
    """Return a list of change dicts between two timelines."""
    changes = []
    b, n = base["clips"], new["clips"]
    for cid in sorted(set(b) | set(n)):
        if cid not in n:
            changes.append({"op": "remove", "clip": cid})
        elif cid not in b:
            changes.append({"op": "add", "clip": cid, "value": copy.deepcopy(n[cid])})
        else:
            fb, fn = flatten(b[cid]), flatten(n[cid])
            for p in sorted(set(fb) | set(fn)):
                if fb.get(p) != fn.get(p):
                    changes.append({"op": "set", "clip": cid, "path": p,
                                    "old": fb.get(p), "new": fn.get(p)})
    return changes


def describe(ch):
    c = ch["clip"]
    if ch["op"] == "add":
        v = ch["value"]
        return f"add {c} ({v['asset']} on track {v['track']} @ {v['start']}f, {v['dur']}f)"
    if ch["op"] == "remove":
        return f"remove {c}"
    return f"{c}.{ch['path']}: {ch['old']!r} -> {ch['new']!r}"


def overlaps(tl):
    """Clips on the same track whose frame ranges intersect."""
    by_track = {}
    for cid, c in tl["clips"].items():
        by_track.setdefault(c["track"], []).append((c["start"], c["start"] + c["dur"], cid))
    found = []
    for track, items in sorted(by_track.items()):
        items.sort()
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if items[j][0] >= items[i][1]:
                    break
                found.append({"track": track, "a": items[i][2], "b": items[j][2]})
    return found
