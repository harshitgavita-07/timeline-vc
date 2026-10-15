import copy, io, os, subprocess, sys, tempfile, unittest, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tlvc.model import diff, overlaps, validate
from tlvc.merge import merge3, apply_resolution
from tlvc.store import Repo


def clip(track=0, start=0, dur=30, asset="a.mp4", inn=0, fx=None):
    return {"track": track, "start": start, "dur": dur, "asset": asset, "in": inn, "effects": fx or {}}


def tl(**clips):
    return {"fps": 30, "clips": clips}


BASE = tl(a=clip(0, 0, 30), b=clip(0, 30, 30, "b.mp4"), c=clip(1, 0, 60, "c.wav"))


class MergeTests(unittest.TestCase):
    def test_diff_is_semantic(self):
        n = copy.deepcopy(BASE); n["clips"]["a"]["start"] = 5; del n["clips"]["c"]
        ops = {(d["op"], d["clip"], d.get("path")) for d in diff(BASE, n)}
        self.assertEqual(ops, {("set", "a", "start"), ("remove", "c", None)})

    def test_disjoint_edits_merge_cleanly(self):
        o, t = copy.deepcopy(BASE), copy.deepcopy(BASE)
        o["clips"]["a"]["effects"]["blur"] = {"r": 3}
        t["clips"]["b"]["dur"] = 20
        m, c = merge3(BASE, o, t)
        self.assertEqual(c, [])
        self.assertEqual(m["clips"]["a"]["effects"], {"blur": {"r": 3}})
        self.assertEqual(m["clips"]["b"]["dur"], 20)

    def test_different_fields_of_same_clip_merge(self):
        o, t = copy.deepcopy(BASE), copy.deepcopy(BASE)
        o["clips"]["a"]["start"] = 2; t["clips"]["a"]["dur"] = 10
        m, c = merge3(BASE, o, t)
        self.assertEqual(c, [])
        self.assertEqual((m["clips"]["a"]["start"], m["clips"]["a"]["dur"]), (2, 10))

    def test_same_field_conflict_and_resolution(self):
        o, t = copy.deepcopy(BASE), copy.deepcopy(BASE)
        o["clips"]["a"]["asset"] = "x.mp4"; t["clips"]["a"]["asset"] = "y.mp4"
        m, c = merge3(BASE, o, t)
        self.assertEqual([(x["kind"], x["path"]) for x in c], [("field", "asset")])
        self.assertEqual(m["clips"]["a"]["asset"], "x.mp4")
        apply_resolution(m, c[0], "theirs")
        self.assertEqual(m["clips"]["a"]["asset"], "y.mp4")

    def test_identical_change_both_sides_is_not_conflict(self):
        o, t = copy.deepcopy(BASE), copy.deepcopy(BASE)
        o["clips"]["c"]["start"] = 7; t["clips"]["c"]["start"] = 7
        self.assertEqual(merge3(BASE, o, t)[1], [])

    def test_remove_vs_edit_conflicts_but_remove_vs_untouched_wins(self):
        o, t = copy.deepcopy(BASE), copy.deepcopy(BASE)
        del o["clips"]["a"]; t["clips"]["a"]["dur"] = 5; del t["clips"]["b"]
        m, c = merge3(BASE, o, t)
        self.assertEqual([x["kind"] for x in c], ["remove-edit"])
        self.assertNotIn("b", m["clips"])
        apply_resolution(m, c[0], "theirs")
        self.assertEqual(m["clips"]["a"]["dur"], 5)

    def test_add_add(self):
        o, t = copy.deepcopy(BASE), copy.deepcopy(BASE)
        o["clips"]["n"] = clip(2, 0, 10, "o.png"); t["clips"]["n"] = clip(2, 50, 10, "t.png")
        self.assertEqual(merge3(BASE, o, t)[1][0]["kind"], "add-add")

    def test_semantic_overlap_without_field_conflict(self):
        # Each side moves a different clip into the same gap on track 2.
        base = tl(a=clip(2, 100, 30), b=clip(2, 300, 30, "b.mp4"))
        o, t = copy.deepcopy(base), copy.deepcopy(base)
        o["clips"]["a"]["start"] = 200; t["clips"]["b"]["start"] = 210
        m, c = merge3(base, o, t)
        self.assertEqual([(x["kind"], x["track"]) for x in c], [("overlap", 2)])

    def test_merge_is_symmetric_when_clean(self):
        o, t = copy.deepcopy(BASE), copy.deepcopy(BASE)
        o["clips"]["a"]["start"] = 2; t["clips"]["c"]["track"] = 3
        self.assertEqual(merge3(BASE, o, t)[0], merge3(BASE, t, o)[0])

    def test_validate_rejects_bad_clip(self):
        with self.assertRaises(ValueError):
            validate({"clips": {"a": {"track": 0, "start": 0, "dur": 0, "asset": "x", "in": 0}}})
        with self.assertRaises(ValueError):
            validate({"clips": {"a": {"track": 0, "start": 1.5, "dur": 3, "asset": "x", "in": 0}}})

    def test_overlaps_touching_is_fine(self):
        self.assertEqual(overlaps(tl(a=clip(0, 0, 30), b=clip(0, 30, 30))), [])


class RepoCliTests(unittest.TestCase):
    def run_cli(self, d, *args):
        env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        p = subprocess.run([sys.executable, "-m", "tlvc", *args], cwd=d, env=env, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def edit(self, d, fn):
        p = os.path.join(d, "timeline.json"); t = json.load(open(p)); fn(t); json.dump(t, open(p, "w"))

    def test_branch_merge_conflict_resolve_continue(self):
        with tempfile.TemporaryDirectory() as d:
            json.dump(BASE, open(os.path.join(d, "timeline.json"), "w"))
            self.assertEqual(self.run_cli(d, "init")[0], 0)
            self.run_cli(d, "commit", "-m", "base")
            self.run_cli(d, "branch", "color")
            self.edit(d, lambda t: t["clips"]["a"].update(asset="main.mp4", **{"in": 3}))
            self.run_cli(d, "commit", "-m", "main edit")
            self.run_cli(d, "checkout", "color")
            self.edit(d, lambda t: (t["clips"]["a"].update(asset="color.mp4"), t["clips"]["b"]["effects"].update(grade={"lut": "warm"})))
            self.run_cli(d, "commit", "-m", "color edit")
            self.run_cli(d, "checkout", "main")
            rc, out = self.run_cli(d, "merge", "color")
            self.assertEqual(rc, 1); self.assertIn("a.asset", out)
            self.assertEqual(self.run_cli(d, "commit", "-m", "x")[0], 1)  # blocked mid-merge
            self.assertEqual(self.run_cli(d, "resolve", "0", "theirs")[0], 0)
            rc, out = self.run_cli(d, "merge", "--continue")
            self.assertEqual(rc, 0, out)
            t = json.load(open(os.path.join(d, "timeline.json")))
            self.assertEqual(t["clips"]["a"]["asset"], "color.mp4")
            self.assertEqual(t["clips"]["a"]["in"], 3)  # non-conflicting edit kept
            self.assertEqual(t["clips"]["b"]["effects"], {"grade": {"lut": "warm"}})

    def test_overlap_must_be_fixed_by_editing(self):
        base = tl(a=clip(2, 100, 30), b=clip(2, 300, 30, "b.mp4"))
        with tempfile.TemporaryDirectory() as d:
            json.dump(base, open(os.path.join(d, "timeline.json"), "w"))
            self.run_cli(d, "init"); self.run_cli(d, "commit", "-m", "base"); self.run_cli(d, "branch", "x")
            self.edit(d, lambda t: t["clips"]["a"].update(start=200)); self.run_cli(d, "commit", "-m", "m")
            self.run_cli(d, "checkout", "x")
            self.edit(d, lambda t: t["clips"]["b"].update(start=210)); self.run_cli(d, "commit", "-m", "x")
            self.run_cli(d, "checkout", "main")
            self.assertEqual(self.run_cli(d, "merge", "x")[0], 1)
            self.assertEqual(self.run_cli(d, "merge", "--continue")[0], 1)  # still overlapping
            self.edit(d, lambda t: t["clips"]["b"].update(start=240))
            self.assertEqual(self.run_cli(d, "merge", "--continue")[0], 0)

    def test_dirty_tree_blocks_checkout_and_merge(self):
        with tempfile.TemporaryDirectory() as d:
            json.dump(BASE, open(os.path.join(d, "timeline.json"), "w"))
            self.run_cli(d, "init"); self.run_cli(d, "commit", "-m", "base"); self.run_cli(d, "branch", "f")
            self.edit(d, lambda t: t["clips"]["a"].update(dur=9))
            self.assertEqual(self.run_cli(d, "checkout", "f")[0], 1)
            self.assertEqual(self.run_cli(d, "merge", "f")[0], 1)
            self.assertEqual(json.load(open(os.path.join(d, "timeline.json")))["clips"]["a"]["dur"], 9)

    def test_fast_forward(self):
        with tempfile.TemporaryDirectory() as d:
            json.dump(BASE, open(os.path.join(d, "timeline.json"), "w"))
            self.run_cli(d, "init"); self.run_cli(d, "commit", "-m", "base"); self.run_cli(d, "branch", "f")
            self.run_cli(d, "checkout", "f"); self.edit(d, lambda t: t["clips"]["a"].update(dur=9))
            self.run_cli(d, "commit", "-m", "f"); self.run_cli(d, "checkout", "main")
            self.assertIn("fast-forward", self.run_cli(d, "merge", "f")[1])


if __name__ == "__main__":
    unittest.main()
