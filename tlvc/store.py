"""Content-addressed commit store in .tlvc/ (commits are full snapshots)."""
import hashlib, json, os, time
from .model import validate

DIR = ".tlvc"


def _dump(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"))


class Repo:
    def __init__(self, root="."):
        self.root = os.path.abspath(root)
        self.d = os.path.join(self.root, DIR)

    def _p(self, *a):
        return os.path.join(self.d, *a)

    def init(self, timeline_file="timeline.json"):
        if os.path.exists(self.d):
            raise RuntimeError("already initialised")
        os.makedirs(self._p("objects")); os.makedirs(self._p("heads"))
        self._w("HEAD", "main")
        self._w("config.json", _dump({"file": timeline_file}))

    def _w(self, name, text):
        with open(self._p(name), "w") as f:
            f.write(text)

    def _r(self, name):
        with open(self._p(name)) as f:
            return f.read()

    @property
    def file(self):
        return os.path.join(self.root, json.loads(self._r("config.json"))["file"])

    def branch(self):
        return self._r("HEAD").strip()

    def head(self, branch=None):
        p = self._p("heads", branch or self.branch())
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return f.read().strip()

    def branches(self):
        return sorted(os.listdir(self._p("heads")))

    def get(self, h):
        with open(self._p("objects", h + ".json")) as f:
            return json.load(f)

    def resolve_ref(self, ref):
        if ref in self.branches():
            return self.head(ref)
        matches = [f[:-5] for f in os.listdir(self._p("objects")) if f.startswith(ref)]
        if len(matches) != 1:
            raise KeyError(f"unknown or ambiguous ref {ref!r}")
        return matches[0]

    def read_working(self):
        with open(self.file) as f:
            return validate(json.load(f))

    def write_working(self, tl):
        with open(self.file, "w") as f:
            json.dump(tl, f, indent=2, sort_keys=True); f.write("\n")

    def commit(self, message, parents=None, timeline=None):
        tl = validate(timeline if timeline is not None else self.read_working())
        if parents is None:
            parents = [self.head()] if self.head() else []
        obj = {"parents": parents, "timeline": tl, "message": message, "time": int(time.time())}
        h = hashlib.sha256(_dump(obj).encode()).hexdigest()[:12]
        self._w(os.path.join("objects", h + ".json"), _dump(obj))
        self._w(os.path.join("heads", self.branch()), h)
        return h

    def create_branch(self, name, at=None):
        h = at or self.head()
        if name in self.branches():
            raise RuntimeError(f"branch {name} exists")
        self._w(os.path.join("heads", name), h)

    def checkout(self, name):
        h = self.head(name)
        if h is None:
            raise KeyError(f"no branch {name}")
        self._w("HEAD", name)
        self.write_working(self.get(h)["timeline"])

    def ancestors(self, h):
        """All ancestors of h with their distance from h (BFS)."""
        seen, q = {h: 0}, [h]
        while q:
            cur = q.pop(0)
            for p in self.get(cur)["parents"]:
                if p not in seen:
                    seen[p] = seen[cur] + 1
                    q.append(p)
        return seen

    def merge_base(self, a, b):
        aa, bb = self.ancestors(a), self.ancestors(b)
        common = set(aa) & set(bb)
        if not common:
            return None
        return min(common, key=lambda h: (aa[h] + bb[h], h))

    def log(self, h=None):
        h = h or self.head()
        out = []
        for c, _ in sorted(self.ancestors(h).items(), key=lambda kv: (kv[1], -self.get(kv[0])["time"])) if h else []:
            out.append((c, self.get(c)["message"]))
        return out

    # merge state, persisted between a conflicted merge and its resolution
    def save_merge(self, state):
        self._w("MERGE", json.dumps(state, indent=2, sort_keys=True))

    def load_merge(self):
        p = self._p("MERGE")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return json.load(f)

    def clear_merge(self):
        p = self._p("MERGE")
        if os.path.exists(p):
            os.remove(p)
