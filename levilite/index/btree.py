from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _Node(Generic[K, V]):
    keys: list[K] = field(default_factory=list)
    values: list[V] = field(default_factory=list)  # utilisé surtout pour feuilles (MVP)
    children: list["_Node[K, V]"] = field(default_factory=list)
    leaf: bool = True


class BTree(Generic[K, V]):
    """
    B-Tree minimal en mémoire (placeholder MVP).

    Pas persisté; prochain step: pages DBFile + planning SELECT.
    """

    def __init__(self, t: int = 8) -> None:
        if t < 2:
            raise ValueError("minimum degree t must be >= 2")
        self.t = t
        self.root: _Node[K, V] = _Node()

    def get(self, key: K) -> Optional[V]:
        n = self.root
        while True:
            i = 0
            while i < len(n.keys) and key > n.keys[i]:
                i += 1
            if i < len(n.keys) and key == n.keys[i]:
                return n.values[i] if n.leaf else None
            if n.leaf:
                return None
            n = n.children[i]

    def put(self, key: K, value: V) -> None:
        r = self.root
        if len(r.keys) == 2 * self.t - 1:
            s: _Node[K, V] = _Node(leaf=False, children=[r])
            self._split_child(s, 0)
            self.root = s
            self._insert_nonfull(s, key, value)
        else:
            self._insert_nonfull(r, key, value)

    def _split_child(self, parent: _Node[K, V], i: int) -> None:
        t = self.t
        y = parent.children[i]
        z: _Node[K, V] = _Node(leaf=y.leaf)

        median_key = y.keys[t - 1]
        median_val = y.values[t - 1] if y.leaf else None

        z.keys = y.keys[t:]
        y.keys = y.keys[: t - 1]

        if y.leaf:
            z.values = y.values[t:]
            y.values = y.values[: t - 1]
        else:
            z.children = y.children[t:]
            y.children = y.children[:t]

        parent.keys.insert(i, median_key)
        if parent.leaf:
            parent.values.insert(i, median_val)  # unused
        parent.children.insert(i + 1, z)

    def _insert_nonfull(self, node: _Node[K, V], key: K, value: V) -> None:
        i = len(node.keys) - 1
        if node.leaf:
            node.keys.append(key)
            node.values.append(value)
            j = len(node.keys) - 2
            while j >= 0 and node.keys[j] > key:
                node.keys[j + 1] = node.keys[j]
                node.values[j + 1] = node.values[j]
                j -= 1
            node.keys[j + 1] = key
            node.values[j + 1] = value
            return

        while i >= 0 and key < node.keys[i]:
            i -= 1
        i += 1
        if len(node.children[i].keys) == 2 * self.t - 1:
            self._split_child(node, i)
            if key > node.keys[i]:
                i += 1
        self._insert_nonfull(node.children[i], key, value)


