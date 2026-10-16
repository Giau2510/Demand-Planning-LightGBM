"""Auditable TreeSHAP: a line-by-line port of LightGBM v4.7.0's own implementation (src/io/tree.cpp:
Tree::ExtendPath, Tree::UnwindPath, Tree::UnwoundPathSum, Tree::TreeSHAP, Tree::ExpectedValue; include/LightGBM/tree.h:
Decision, NumericalDecision, CategoricalDecision, data_count) that also records every term it adds.

LightGBM's predict(pred_contrib=True) only returns the final values. This engine recomputes them from the SAME model
file (parsed from its text, so thresholds/leaf values/counts are the exact doubles LightGBM loads) and the SAME
feature row, in the same order of floating-point operations, and keeps each term:

    phi[f] += w * (one_fraction - zero_fraction) * leaf_value          (tree.cpp, leaf case of TreeSHAP)

for every tree, every leaf, and every feature f on the leaf's "unique path". The engine is only trusted when its
result equals LightGBM's own output (verify()); otherwise the trace is reported as NOT VERIFIED.

Definitions (TreeSHAP of Lundberg, Erion & Lee 2018, Algorithm 2, "path-dependent" variant, as in LightGBM):
* cover of a node = number of training rows LightGBM recorded for it while building that tree (internal_count /
  leaf_count in the model file; with bagging these are the rows of that iteration's bag).
* zero_fraction of f on a path = product over the splits on f along the path of cover(child) / cover(node): the
  share of the tree's training rows that would take this way if f were unknown.
* one_fraction of f = 1 if the row's own value of f takes every split on f along the path that way, else 0.
* w = Shapley weight of f on that path: sum over subsets S of the other features on the path of
  |S|!(d-|S|-1)!/d! x (product of one_fractions of S) x (product of zero_fractions of the rest), computed by the
  polynomial ExtendPath / UnwoundPathSum recursion.
* base value = sum over trees of ExpectedValue = sum over leaves (leaf_count / root count) x leaf_value.
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field

import numpy as np

K_ZERO_THRESHOLD = float(np.float32(1e-35))      # meta.h: const double kZeroThreshold = 1e-35f;
K_CATEGORICAL_MASK = 1
K_DEFAULT_LEFT_MASK = 2
MISSING_NONE, MISSING_ZERO, MISSING_NAN = 0, 1, 2
LIGHTGBM_SOURCE = "LightGBM v4.7.0 src/io/tree.cpp (TreeSHAP), include/LightGBM/tree.h (Decision)"


class TraceError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class Tree:
    index: int
    num_leaves: int
    split_feature: list[int] = field(default_factory=list)
    threshold: list[float] = field(default_factory=list)
    decision_type: list[int] = field(default_factory=list)
    left_child: list[int] = field(default_factory=list)
    right_child: list[int] = field(default_factory=list)
    leaf_value: list[float] = field(default_factory=list)
    leaf_count: list[int] = field(default_factory=list)
    internal_count: list[int] = field(default_factory=list)
    cat_boundaries: list[int] = field(default_factory=list)
    cat_threshold: list[int] = field(default_factory=list)

    def data_count(self, node: int) -> float:
        return float(self.internal_count[node] if node >= 0 else self.leaf_count[~node])

    def expected_value(self) -> float:
        if self.num_leaves == 1:
            return self.leaf_value[0]
        total = float(self.internal_count[0])
        v = 0.0
        for i in range(self.num_leaves):
            v += (self.leaf_count[i] / total) * self.leaf_value[i]
        return v

    def decision(self, fval: float, node: int) -> int:
        dt = self.decision_type[node]
        if dt & K_CATEGORICAL_MASK:
            if math.isnan(fval):
                return self.right_child[node]
            ival = int(fval)                       # static_cast<int> truncates toward zero
            if ival < 0:
                return self.right_child[node]
            cat_idx = int(self.threshold[node])
            lo, hi = self.cat_boundaries[cat_idx], self.cat_boundaries[cat_idx + 1]
            i1 = ival // 32
            if i1 >= hi - lo:
                return self.right_child[node]
            return self.left_child[node] if (self.cat_threshold[lo + i1] >> (ival % 32)) & 1 else self.right_child[node]
        missing = (dt >> 2) & 3
        if math.isnan(fval) and missing != MISSING_NAN:
            fval = 0.0
        if (missing == MISSING_ZERO and -K_ZERO_THRESHOLD <= fval <= K_ZERO_THRESHOLD) or (missing == MISSING_NAN and math.isnan(fval)):
            return self.left_child[node] if dt & K_DEFAULT_LEFT_MASK else self.right_child[node]
        return self.left_child[node] if fval <= self.threshold[node] else self.right_child[node]

    def split_text(self, node: int, names: list[str]) -> str:
        f = names[self.split_feature[node]]
        dt = self.decision_type[node]
        if dt & K_CATEGORICAL_MASK:
            cat_idx = int(self.threshold[node])
            lo, hi = self.cat_boundaries[cat_idx], self.cat_boundaries[cat_idx + 1]
            cats = [w * 32 + b for w, word in enumerate(self.cat_threshold[lo:hi]) for b in range(32) if (word >> b) & 1]
            return f"{f} ∈ {{{', '.join(map(str, cats))}}}"
        missing = ("None", "Zero", "NaN")[(dt >> 2) & 3]
        return f"{f} <= {self.threshold[node]!r} (missing={missing}, default_{'left' if dt & K_DEFAULT_LEFT_MASK else 'right'})"


@dataclass
class Model:
    feature_names: list[str]
    objective: str
    trees: list[Tree]
    sha256: str


def parse_model(text: str) -> Model:
    """Parse LightGBM's text model format (the saved artifact) into exact doubles (Python float() is correctly
    rounded like LightGBM's own parser)."""
    lines = text.splitlines()
    header: dict[str, str] = {}
    trees: list[Tree] = []
    cur: dict[str, str] | None = None
    idx = None

    def flush():
        if cur is None:
            return
        nl = int(cur["num_leaves"])
        t = Tree(index=idx, num_leaves=nl,
                 leaf_value=[float(v) for v in cur["leaf_value"].split()],
                 leaf_count=[int(v) for v in cur.get("leaf_count", "").split()] if nl > 1 else [0])
        if nl > 1:
            t.split_feature = [int(v) for v in cur["split_feature"].split()]
            t.threshold = [float(v) for v in cur["threshold"].split()]
            t.decision_type = [int(v) for v in cur["decision_type"].split()]
            t.left_child = [int(v) for v in cur["left_child"].split()]
            t.right_child = [int(v) for v in cur["right_child"].split()]
            t.internal_count = [int(v) for v in cur["internal_count"].split()]
            if int(cur.get("num_cat", "0")) > 0:
                t.cat_boundaries = [int(v) for v in cur["cat_boundaries"].split()]
                t.cat_threshold = [int(v) for v in cur["cat_threshold"].split()]
        if cur.get("is_linear", "0") not in ("0", ""):
            raise TraceError("UNSUPPORTED_MODEL", "linear trees are not supported")
        trees.append(t)

    for ln in lines:
        if ln.startswith("Tree="):
            flush()
            idx = int(ln[5:])
            cur = {}
            continue
        if ln.startswith("end of trees"):
            flush()
            cur = None
            break
        if "=" in ln:
            k, v = ln.split("=", 1)
            (cur if cur is not None else header)[k] = v
    if int(header.get("num_class", "1")) != 1 or int(header.get("num_tree_per_iteration", "1")) != 1:
        raise TraceError("UNSUPPORTED_MODEL", "only single-output models are supported")
    return Model(feature_names=header.get("feature_names", "").split(), objective=header.get("objective", "").split()[0],
                 trees=trees, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


# ---------------------------------------------------------------- the TreeSHAP recursion (exact port)
def _extend(path: list[list], ud: int, zero: float, one: float, feat: int) -> None:
    # unique_path[ud] = {feature_index, zero_fraction, one_fraction, pweight}
    while len(path) <= ud:
        path.append([0, 0.0, 0.0, 0.0])
    path[ud] = [feat, zero, one, 1.0 if ud == 0 else 0.0]
    for i in range(ud - 1, -1, -1):
        path[i + 1][3] += one * path[i][3] * (i + 1) / float(ud + 1)
        path[i][3] = zero * path[i][3] * (ud - i) / float(ud + 1)


def _unwind(path: list[list], ud: int, pi: int) -> None:
    one, zero = path[pi][2], path[pi][1]
    nop = path[ud][3]
    for i in range(ud - 1, -1, -1):
        if one != 0:
            tmp = path[i][3]
            path[i][3] = nop * (ud + 1) / float((i + 1) * one)
            nop = tmp - path[i][3] * zero * (ud - i) / float(ud + 1)
        else:
            path[i][3] = (path[i][3] * (ud + 1)) / float(zero * (ud - i))
    for i in range(pi, ud):
        path[i][0], path[i][1], path[i][2] = path[i + 1][0], path[i + 1][1], path[i + 1][2]


def _unwound_sum(path: list[list], ud: int, pi: int) -> float:
    one, zero = path[pi][2], path[pi][1]
    nop = path[ud][3]
    total = 0.0
    for i in range(ud - 1, -1, -1):
        if one != 0:
            tmp = nop * (ud + 1) / float((i + 1) * one)
            total += tmp
            nop = path[i][3] - tmp * zero * ((ud - i) / float(ud + 1))
        else:
            total += (path[i][3] / zero) / ((ud - i) / float(ud + 1))
    return total


def trace_tree(t: Tree, x: list[float], phi: list[float], comps: list | None, routes: dict | None) -> int:
    """TreeSHAP for one tree; phi is accumulated in LightGBM's order. Returns the leaf the row actually reaches."""
    actual_leaf = None

    def rec(node: int, ud: int, parent: list[list], pz: float, po: float, pf: int, route: list):
        nonlocal actual_leaf
        path = [list(e) for e in parent[:ud]]          # std::copy(parent, parent + unique_depth, unique_path)
        _extend(path, ud, pz, po, pf)
        if node < 0:
            leaf = ~node
            if all(r[2] for r in route):
                actual_leaf = leaf
            if routes is not None:
                routes[(t.index, leaf)] = route
            v = t.leaf_value[leaf]
            for i in range(1, ud + 1):
                w = _unwound_sum(path, ud, i)
                el = path[i]
                term = w * (el[2] - el[1]) * v
                phi[el[0]] += term
                if comps is not None:
                    comps.append((t.index, leaf, el[0], el[2], el[1], w, v, term))
            return
        f = t.split_feature[node]
        hot = t.decision(x[f], node)
        cold = t.right_child[node] if hot == t.left_child[node] else t.left_child[node]
        w = t.data_count(node)
        hz, cz = t.data_count(hot) / w, t.data_count(cold) / w
        iz, io = 1.0, 1.0
        pi = 0
        while pi <= ud:
            if path[pi][0] == f:
                break
            pi += 1
        if pi != ud + 1:
            iz, io = path[pi][1], path[pi][2]
            _unwind(path, ud, pi)
            ud -= 1
        rec(hot, ud + 1, path, hz * iz, io, f, route + [(node, hot, True, hz)])
        rec(cold, ud + 1, path, cz * iz, 0.0, f, route + [(node, cold, False, cz)])

    if t.num_leaves > 1:
        rec(0, 0, [], 1.0, 1.0, -1, [])
    else:
        actual_leaf = 0
    return actual_leaf


def trace_row(m: Model, x: list[float], collect: bool = True, time_limit_s: float = 60.0,
              max_components: int = 3_000_000) -> dict:
    """phi for every feature + base value; optionally every term (component) and every leaf route."""
    nf = len(m.feature_names)
    if len(x) != nf:
        raise TraceError("FEATURE_COUNT_MISMATCH", f"row has {len(x)} values, model has {nf} features")
    phi = [0.0] * (nf + 1)
    comps: list | None = [] if collect else None
    routes: dict | None = {} if collect else None
    leaves = []
    t0 = time.monotonic()
    for t in m.trees:
        phi[nf] += t.expected_value()                 # output[num_features] += ExpectedValue();
        leaves.append(trace_tree(t, x, phi, comps, routes))
        if time.monotonic() - t0 > time_limit_s:
            raise TraceError("TRACE_TIMEOUT", f"more than {time_limit_s}s after {t.index + 1} trees")
        if comps is not None and len(comps) > max_components:
            raise TraceError("TRACE_TOO_LARGE", f"more than {max_components} terms")
    return {"phi": phi[:nf], "base_value": phi[nf], "leaves": leaves, "components": comps, "routes": routes,
            "seconds": time.monotonic() - t0}


def row_hash(x) -> str:
    return hashlib.sha256(np.asarray(x, dtype=np.float32).tobytes()).hexdigest()
