import io
import json
import stat
import zipfile

import pytest

from fksync import zips


def _write(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def _zip(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            info = zipfile.ZipInfo("placeholder")
            info.filename = name  # raw: ZipInfo() would turn "\\" into "/" on Windows
            info.external_attr = 0o600 << 16  # what writestr(str) records
            zf.writestr(info, data, zipfile.ZIP_DEFLATED)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "../../outside.json")
    return buf.getvalue()


BUILD = json.dumps({"stamp": "20261102-010203", "live_hash": "ab"}).encode()


def test_pack_only_presets_sorted(tmp_path):
    root = tmp_path / "tree"
    _write(root, {"base/b.info": b"x", "a.json": b"{}", "c.txt": b"y", "base/d.bak": b"z"})
    data = zips.pack(root)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == ["a.json", "base/b.info"]
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in zf.infolist())
        assert zf.read("a.json") == b"{}"
    assert zips.pack(root) == data
    # mtimes do not leak into the bytes
    import os
    os.utime(root / "a.json", (1, 1))
    assert zips.pack(root) == data


def test_pack_missing_root_is_empty_zip(tmp_path):
    with zipfile.ZipFile(io.BytesIO(zips.pack(tmp_path / "nope"))) as zf:
        assert zf.namelist() == []


def test_unpack_build_ok(tmp_path):
    dest = tmp_path / "out"
    data = _zip({"BUILD.json": BUILD, "base/SUNLU PLA+ 2.0 @Bambu Lab H2D 0.4 nozzle.json": b"{}",
                 "base/SUNLU PLA+ 2.0 @Bambu Lab H2D 0.4 nozzle.info": b"setting_id = \n"})
    build = zips.unpack_build(data, dest)
    assert build == json.loads(BUILD)
    assert (dest / "BUILD.json").read_bytes() == BUILD
    assert (dest / "base" / "SUNLU PLA+ 2.0 @Bambu Lab H2D 0.4 nozzle.json").read_bytes() == b"{}"
    assert sorted(p.name for p in dest.parent.iterdir()) == ["appdata", "local", "out"]  # no temp dir left  # no temp dir left behind


@pytest.mark.parametrize("bad", [
    "../x.json", "base/../../x.json", "other/x.json", "/abs.json", "C:/x.json", "base\\x.json",
    "base/C:x.json", "base/x.txt", "base/.json", "base/CON.json", "base/x .json", "base/sub/x.json",
    "build.json", "base/x\x01.json",
])
def test_unpack_build_refuses_unsafe(tmp_path, bad):
    work = tmp_path / "work" / "deep"
    work.mkdir(parents=True)
    dest = work / "out"
    data = _zip({"BUILD.json": BUILD, "base/ok.json": b"{}", bad: b"{}"})
    with pytest.raises(ValueError):
        zips.unpack_build(data, dest)
    assert not dest.exists()
    assert list(work.iterdir()) == []
    assert not (work.parent / "x.json").exists()
    assert not (tmp_path / "x.json").exists()


def test_unpack_build_refuses_symlink_missing_build_and_garbage(tmp_path):
    dest = tmp_path / "out"
    for data in (_zip({"BUILD.json": BUILD}, symlink="base/link.json"),
                 _zip({"base/ok.json": b"{}"}),
                 _zip({"BUILD.json": b"[1, 2]"}),
                 _zip({"BUILD.json": b"not json"}),
                 _zip({"BUILD.json": BUILD, "base/a.json": b"1", "base/A.JSON": b"2"}),
                 b"not a zip at all"):
        with pytest.raises(ValueError):
            zips.unpack_build(data, dest)
        assert not dest.exists()


def test_unpack_build_refuses_bomb(tmp_path, monkeypatch):
    dest = tmp_path / "out"
    monkeypatch.setattr(zips, "MAX_BUILD_UNCOMPRESSED", 1000)
    data = _zip({"BUILD.json": BUILD, "base/big.json": b" " * 2000})
    with pytest.raises(ValueError):
        zips.unpack_build(data, dest)
    assert not dest.exists()


def test_unpack_build_limit_is_64_mib():
    assert zips.MAX_BUILD_UNCOMPRESSED == 64 * 1024 * 1024


def test_unpack_build_refuses_nonempty_dest(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "keep.txt").write_text("x")
    with pytest.raises(ValueError):
        zips.unpack_build(_zip({"BUILD.json": BUILD}), dest)
    assert sorted(p.name for p in dest.iterdir()) == ["keep.txt"]


def test_pack_enforces_upload_limits(tmp_path, monkeypatch):
    root = tmp_path / "live"
    _write(root, {"a.json": b"{}", "base/b.json": b"x" * 100, "base/b.info": b"y"})
    assert zips.pack(root, max_bytes=1 << 20)
    with pytest.raises(zips.TooLarge, match="too large"):
        zips.pack(root, max_bytes=10)
    monkeypatch.setattr(zips, "MAX_FILE", 50)
    with pytest.raises(zips.TooLarge, match="b.json"):
        zips.pack(root)
    monkeypatch.setattr(zips, "MAX_FILE", 4 << 20)
    monkeypatch.setattr(zips, "MAX_ENTRIES", 2)
    with pytest.raises(zips.TooLarge, match="3 files"):
        zips.pack(root)
    monkeypatch.setattr(zips, "MAX_ENTRIES", 20000)
    monkeypatch.setattr(zips, "MAX_TOTAL", 50)
    with pytest.raises(zips.TooLarge):
        zips.pack(root)
    assert issubclass(zips.TooLarge, ValueError)


def test_upload_limit_values():
    assert (zips.MAX_FILE, zips.MAX_ENTRIES, zips.MAX_TOTAL) == (4 << 20, 20000, 512 << 20)
    assert (zips.LIVE_MAX, zips.SYSTEM_MAX) == (32 << 20, 64 << 20)
