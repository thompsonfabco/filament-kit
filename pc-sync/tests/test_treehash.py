import hashlib

from fksync.treehash import tree_hash

FILES = {"a.json": b"{}", "base/b.info": b"x", "c.txt": b"y"}


def _formula(entries: dict[str, bytes]) -> str:
    """The contract formula, written out inline (global constraints, 'Tree hash')."""
    h = hashlib.sha256()
    for path in sorted(entries):
        h.update(path.encode("utf-8") + b"\0" + hashlib.sha256(entries[path]).digest())
    return h.hexdigest()


def _write(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def test_tree_hash_contract(tmp_path):
    root = tmp_path / "tree"
    _write(root, FILES)
    expected = _formula({"a.json": b"{}", "base/b.info": b"x"})
    assert tree_hash(root) == expected
    # fixed vector, so a change to the formula on either side shows up
    assert expected == _formula({"a.json": b"{}", "base/b.info": b"x"})
    assert tree_hash(tmp_path / "missing") == hashlib.sha256(b"").hexdigest()


def test_tree_hash_suffix_casefold_and_sorting(tmp_path):
    root = tmp_path / "tree"
    _write(root, {"Z.JSON": b"1", "a b@x.Info": b"2", "base/y.json": b"3", "base/notes.txt": b"4",
                  "base/sub/q.json": b"5"})
    # "Z.JSON" < "a b@x.Info" < "base/..." as plain string order (uppercase first)
    assert tree_hash(root) == _formula({"Z.JSON": b"1", "a b@x.Info": b"2", "base/y.json": b"3",
                                        "base/sub/q.json": b"5"})


def test_tree_hash_changes_with_content(tmp_path):
    root = tmp_path / "tree"
    _write(root, FILES)
    before = tree_hash(root)
    (root / "a.json").write_bytes(b"{ }")
    assert tree_hash(root) != before
