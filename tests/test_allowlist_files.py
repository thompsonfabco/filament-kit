"""The allow-lists are folders, one file per source file (tests/allowlist_files.py): sorted, no duplicate line, every line
in the file named for its source, and no old single-file list left behind."""
import pytest

from allowlist_files import DIR, KEYS, ROOT, key_path, problems


def test_no_single_file_list_is_left():
    assert not sorted(p.name for p in (ROOT / "tests").glob("*_allowlist.txt"))


def test_the_folders_are_the_lists():
    assert sorted(p.name for p in DIR.iterdir() if p.is_dir()) == sorted(KEYS)
    assert [p.name for p in DIR.iterdir() if p.is_file()] == ["README.md"]


@pytest.mark.parametrize("name", sorted(KEYS))
def test_every_list_keeps_the_rules(name):
    assert problems(DIR / name, KEYS[name]) == []


def _planted(tmp_path, body, name="a__b.js.txt"):
    (tmp_path / name).write_text(body, encoding="utf-8", newline="\n")
    return problems(tmp_path, key_path)


def test_a_clean_file_passes(tmp_path):
    assert _planted(tmp_path, "a/b.js | x | 1 | r\na/b.js | y | 1 | r\n") == []


def test_an_unsorted_file_fails(tmp_path):
    assert any("not sorted" in m for m in _planted(tmp_path, "a/b.js | y | 1 | r\na/b.js | x | 1 | r\n"))


def test_a_duplicate_line_fails(tmp_path):
    assert any("listed twice" in m for m in _planted(tmp_path, "a/b.js | x | 1 | r\na/b.js | x | 1 | r\n"))


def test_a_line_of_another_source_fails(tmp_path):
    assert any("belongs in" in m for m in _planted(tmp_path, "a/c.js | x | 1 | r\n"))


def test_a_cr_a_blank_line_and_a_missing_newline_fail(tmp_path):
    assert any("CR" in m for m in _planted(tmp_path, "a/b.js | x | 1 | r\r\n"))
    assert any("blank" in m for m in _planted(tmp_path, "a/b.js | x | 1 | r\n\n"))
    assert any("newline" in m for m in _planted(tmp_path, "a/b.js | x | 1 | r"))
