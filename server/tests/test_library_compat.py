"""A signed library installs what this kit can read and says what it couldn't. Anything unsigned, and the owner's own additions,
stay strict. Too much gone, a wrong hash or a wrong path still refuses, and the current library stays."""
from __future__ import annotations

import hashlib
import json

import pytest

from filament_kit import cli, library
from test_library import served  # noqa: F401  (fixture)
from test_library_on_request import env, fixture_files, fresh, tar_bytes  # noqa: F401  (fixtures)
from test_library_signed import URL, release_web
from test_updates import key  # noqa: F401  (fixture)


def _rehash(files: dict[str, bytes], version: int = 90) -> dict[str, bytes]:
    idx = json.loads(files["index.json"])
    idx["library_version"] = version
    for r in idx["entries"]:
        r["sha256"] = hashlib.sha256(files[r["path"]]).hexdigest()
    return {**files, "index.json": json.dumps(idx).encode()}


def _paths(files) -> list[str]:
    return [r["path"] for r in json.loads(files["index.json"])["entries"]]


def _change(files, path, fn) -> None:
    e = json.loads(files[path])
    fn(e)
    files[path] = json.dumps(e).encode()


def _install(key, files):  # noqa: F811
    return library.update(URL, opener=release_web(key, tar_bytes(_rehash(files))))


def test_a_new_field_key_is_dropped_and_the_entry_stays(fresh, key):  # noqa: F811
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e["fields"].update(a_new_field=["1"]))
    _change(files, p, lambda e: e.update(a_new_top_key="x"))
    r = _install(key, files)
    assert r.error is None and r.changed
    lib = library.load()
    assert lib.source == "updated" and lib.version == 90
    assert library.last_check()["ok"] is True and library.skipped() == {"entries": 0, "parts": 2}
    stored = library._current()[1]
    assert stored["read_by"] and len(stored["entries"]) == len(_paths(files))


def test_a_wider_range_drops_that_field_only(fresh, key):  # noqa: F811
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e["fields"].update(filament_density=["4.0"]))
    assert _install(key, files).error is None
    root, idx, _ = library._current()
    saved = json.loads((root / p).read_bytes())
    assert "filament_density" not in saved["fields"] and saved["product"]
    row = next(r for r in idx["entries"] if r["path"] == p)
    assert row["sha256"] == hashlib.sha256((root / p).read_bytes()).hexdigest()    # what is on disk is what is listed


def test_a_published_range_it_cant_read_goes_alone(fresh, key):  # noqa: F811
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e["published_ranges"].update(new_range="1-2"))
    assert _install(key, files).error is None
    assert library.skipped()["parts"] == 1


def test_an_entry_missing_something_required_goes_whole(fresh, key, monkeypatch):  # noqa: F811
    monkeypatch.setattr(library, "MAX_DROPPED", 0.5)      # the fixture has three entries
    files = fixture_files()
    paths = _paths(files)
    _change(files, paths[0], lambda e: e.pop("material"))
    r = _install(key, files)
    assert r.error is None
    idx = library._current()[1]
    assert paths[0] not in [x["path"] for x in idx["entries"]]
    assert library.skipped()["entries"] == 1


def test_a_new_entry_schema_version_goes_whole(fresh, key, monkeypatch):  # noqa: F811
    monkeypatch.setattr(library, "MAX_DROPPED", 0.5)
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e.update(schema_version=2))
    assert _install(key, files).error is None
    assert library.skipped()["entries"] == 1


def test_too_many_gone_refuses_and_keeps_the_current_library(fresh, key):  # noqa: F811
    assert _install(key, fixture_files()).error is None
    v = library.load().version
    files = fixture_files()
    paths = _paths(files)
    for p in paths[:max(1, len(paths) // 2)]:
        _change(files, p, lambda e: e.pop("material"))
    files = _rehash(files, 91)
    r = library.update(URL, opener=release_web(key, tar_bytes(files)))
    assert r.error and "broken release" in r.error and library.load().version == v


def test_exactly_at_the_ceiling_still_installs(fresh, key, monkeypatch):  # noqa: F811
    files = fixture_files()
    paths = _paths(files)
    monkeypatch.setattr(library, "MAX_DROPPED", 1 / len(paths))
    _change(files, paths[0], lambda e: e.pop("material"))
    assert _install(key, files).error is None


def test_a_wrong_hash_is_still_fatal(fresh, key):  # noqa: F811
    files = _rehash(fixture_files())
    p = _paths(files)[0]
    files[p] = files[p] + b" "
    r = library.update(URL, opener=release_web(key, tar_bytes(files)))
    assert r.error and "sha256" in r.error


def test_a_wrong_path_is_still_fatal(fresh, key):  # noqa: F811
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e.update(product="Something Else Entirely"))
    r = _install(key, files)
    assert r.error and "belongs at" in r.error


def test_another_index_schema_refuses(fresh, key):  # noqa: F811
    files = _rehash(fixture_files())
    idx = json.loads(files["index.json"])
    idx["schema_version"] = 2
    files["index.json"] = json.dumps(idx).encode()
    r = library.update(URL, opener=release_web(key, tar_bytes(files)))
    assert r.error and "schema_version" in r.error


def test_unsigned_stays_strict(fresh, served):  # noqa: F811
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e["fields"].update(a_new_field=["1"]))
    from test_library_on_request import put
    url = put(served, "library.tar.gz", tar_bytes(_rehash(files)))
    r = library.update(url)
    assert r.error and "a_new_field" in r.error


def test_the_owners_own_additions_stay_strict(fresh):  # noqa: F811
    entry = {"schema_version": 1, "vendor": "Acme", "product": "PLA One", "material": "PLA", "bambu_parent": "Bambu PLA Basic",
             "fields": {"a_new_field": ["1"]}}
    with pytest.raises(ValueError):
        library.add_local(json.dumps(entry).encode())


def test_the_same_release_again_does_nothing_until_a_newer_kit_reads_it(fresh, key, monkeypatch):  # noqa: F811
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e["fields"].update(a_new_field=["1"]))
    tar = tar_bytes(_rehash(files))
    assert library.update(URL, opener=release_web(key, tar)).changed is True
    again = library.update(URL, opener=release_web(key, tar))
    assert again.changed is False and library.skipped() == {"entries": 0, "parts": 1}
    monkeypatch.setattr(library, "__version__", "99.0.0")
    assert library.update(URL, opener=release_web(key, tar)).changed is True


def test_a_clean_release_keeps_its_signed_index_as_it_was_and_says_nothing(fresh, key):  # noqa: F811
    files = _rehash(fixture_files())
    assert library.update(URL, opener=release_web(key, tar_bytes(files))).error is None
    assert library.skipped() is None and library.status()["skipped"] is None
    root = library._current()[0]
    assert (root / "index.json").read_bytes() == files["index.json"]


def test_status_says_how_many(fresh, key, monkeypatch, capsys):  # noqa: F811
    files = fixture_files()
    p = _paths(files)[0]
    _change(files, p, lambda e: e["fields"].update(a_new_field=["1"]))
    assert _install(key, files).error is None
    capsys.readouterr()
    cli._library_status_lines()
    assert "1 field left out, which this kit can't read; a newer kit may" in capsys.readouterr().out


SAID = "1 field left out, which this kit can't read; a newer kit may"


def _one_field_too_new(key):  # noqa: F811
    files = fixture_files()
    _change(files, _paths(files)[0], lambda e: e["fields"].update(a_new_field=["1"]))
    assert _install(key, files).error is None


def test_library_status_says_how_many_too(fresh, key, capsys, monkeypatch):  # noqa: F811
    _one_field_too_new(key)
    capsys.readouterr()
    assert cli.main(["library", "status"]) == 0
    assert SAID in capsys.readouterr().out


def test_library_update_says_how_many(fresh, key, capsys, monkeypatch):  # noqa: F811
    files = fixture_files()
    _change(files, _paths(files)[0], lambda e: e["fields"].update(a_new_field=["1"]))
    web = release_web(key, tar_bytes(_rehash(files)))
    real = library.update
    monkeypatch.setattr(library, "update", lambda url=None: real(URL, opener=web))
    monkeypatch.setattr(cli, "_request_rebuild", lambda why: None)
    capsys.readouterr()
    assert cli.main(["library", "update"]) == 0
    assert SAID in capsys.readouterr().out


def test_a_failed_check_doesnt_lose_what_the_library_in_use_left_out(fresh, key):  # noqa: F811
    _one_field_too_new(key)
    r = library.update(URL, opener=release_web(key, b"not a tar"))
    assert r.error and library.last_check()["ok"] is False
    assert library.status()["skipped"] == SAID


def test_the_count_follows_a_rollback_both_ways(fresh, key):  # noqa: F811
    files = _rehash(fixture_files(), 89)
    assert library.update(URL, opener=release_web(key, tar_bytes(files))).error is None
    _one_field_too_new(key)
    assert library.status()["skipped"] == SAID
    library.rollback()
    assert library.status()["version"] == 89 and library.status()["skipped"] is None
    library.rollback()
    assert library.status()["version"] == 90 and library.status()["skipped"] == SAID


def test_one_bad_limit_takes_the_other_with_it(fresh):
    files = fixture_files()
    e = json.loads(files[_paths(files)[0]])
    e["fields"].update(nozzle_temperature_range_low=["999"], nozzle_temperature_range_high=["200"])
    out, gone = library.salvage(e)
    assert out is not None and gone == 2
    assert "nozzle_temperature_range_low" not in out["fields"] and "nozzle_temperature_range_high" not in out["fields"]


def test_salvage_leaves_nothing_invalid():
    assert library.salvage("nope") == (None, 0)
    assert library.salvage({"vendor": "x"})[0] is None
