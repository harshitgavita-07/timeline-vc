"""Three-way timeline merge with structured conflicts.

Per clip and per field: if both sides agree, or only one side changed, the
merge is automatic. If both changed the same field differently, that is a
conflict. Remove-vs-edit is a conflict. After merging, clips that overlap on a
track are reported as a semantic conflict even though no single field clashed
(two editors each placed a different clip into the same gap).
"""
import copy
from .model import flatten, unflatten, overlaps

MISSING = object()


def _val(flat, p):
    return flat.get(p, MISSING)


def merge3(base, ours, theirs):
    """Return (merged_timeline, conflicts). Conflicts keep the 'ours' value in
    the merged timeline until resolved; each conflict records both sides."""
    merged = {"fps": ours.get("fps", base.get("fps")), "clips": {}}
    conflicts = []
    ids = sorted(set(base["clips"]) | set(ours["clips"]) | set(theirs["clips"]))
    for cid in ids:
        b, o, t = (x["clips"].get(cid) for x in (base, ours, theirs))
        if o == t:
            if o is not None:
                merged["clips"][cid] = copy.deepcopy(o)
            continue
        if b is None:  # added on one or both sides
            if o is None:
                merged["clips"][cid] = copy.deepcopy(t)
            elif t is None:
                merged["clips"][cid] = copy.deepcopy(o)
            else:
                merged["clips"][cid] = copy.deepcopy(o)
                conflicts.append({"kind": "add-add", "clip": cid, "ours": o, "theirs": t})
            continue
        if o is None or t is None:  # removed on a side
            survivor, side = (t, "theirs") if o is None else (o, "ours")
            if survivor == b:
                continue  # removal wins, other side did not touch it
            removed_by = "ours" if o is None else "theirs"
            conflicts.append({"kind": "remove-edit", "clip": cid, "removed_by": removed_by,
                              "ours": o, "theirs": t})
            if o is not None:
                merged["clips"][cid] = copy.deepcopy(o)
            continue
        fb, fo, ft = flatten(b), flatten(o), flatten(t)
        out = {}
        for p in sorted(set(fb) | set(fo) | set(ft)):
            vb, vo, vt = _val(fb, p), _val(fo, p), _val(ft, p)
            if vo == vt or vt == vb:
                pick = vo
            elif vo == vb:
                pick = vt
            else:
                pick = vo
                conflicts.append({"kind": "field", "clip": cid, "path": p,
                                  "base": None if vb is MISSING else vb,
                                  "ours": None if vo is MISSING else vo,
                                  "theirs": None if vt is MISSING else vt})
            if pick is not MISSING:
                out[p] = pick
        merged["clips"][cid] = unflatten(out)
    for ov in overlaps(merged):
        conflicts.append({"kind": "overlap", **ov})
    return merged, conflicts


def apply_resolution(merged, conflict, side):
    """Apply 'ours' or 'theirs' for one non-overlap conflict, in place."""
    if side not in ("ours", "theirs"):
        raise ValueError("side must be 'ours' or 'theirs'")
    cid, kind = conflict["clip"], conflict["kind"]
    if kind in ("add-add", "remove-edit"):
        v = conflict[side]
        if v is None:
            merged["clips"].pop(cid, None)
        else:
            merged["clips"][cid] = copy.deepcopy(v)
    elif kind == "field":
        flat = flatten(merged["clips"][cid])
        v = conflict[side]
        if v is None:
            flat.pop(conflict["path"], None)
        else:
            flat[conflict["path"]] = copy.deepcopy(v)
        merged["clips"][cid] = unflatten(flat)
    else:
        raise ValueError("overlap conflicts are fixed by editing the timeline (move a clip)")
