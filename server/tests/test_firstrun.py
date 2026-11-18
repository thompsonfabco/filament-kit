"""AF1: the first-run file (R82 section 4 point 6)."""
import os

import pytest

from filament_kit import config, firstrun


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    return tmp_path


def f():
    return config.paths().state / "firstrun.xml"


def test_no_file_reads_as_hidden():            # an updated Hub starts with the panel hidden
    st = firstrun.load()
    assert st.hidden and not st.shows and not st.present


def test_a_first_install_shows_the_panel_and_remembers_what_it_asked():
    assert firstrun.install_first(["name", "features", "nonsense"])
    st = firstrun.load()
    assert st.shows and st.answered == {"name", "features"} and not st.finished
    assert 'hidden="false"' in f().read_text()


def test_a_second_install_does_not_touch_the_file():
    firstrun.install_first(["name"])
    firstrun.set_hidden(True)
    assert firstrun.install_first([]) is False
    assert firstrun.load().hidden and firstrun.load().answered == {"name"}


def test_hide_show_mark_finish():
    firstrun.install_first()
    assert firstrun.set_hidden(True) and firstrun.load().hidden
    assert firstrun.set_hidden(False) and firstrun.load().shows
    assert firstrun.mark("storage") and firstrun.load().answered == {"storage"}
    assert firstrun.mark("storage") and firstrun.load().answered == {"storage"}
    assert firstrun.finish() and firstrun.load().finished and not firstrun.load().shows
    with pytest.raises(ValueError):
        firstrun.mark("printer")


def test_a_mark_on_an_updated_hub_keeps_the_panel_hidden():
    assert firstrun.mark("name")
    st = firstrun.load()
    assert st.hidden and st.answered == {"name"} and st.present


def test_restore_hides_whatever_the_backup_carried():
    firstrun.install_first(["name"])
    assert firstrun.hide_after_restore()
    assert firstrun.load().hidden and firstrun.load().answered == {"name"}
    f().unlink()                                    # a backup from before the panel
    assert firstrun.hide_after_restore() and firstrun.load().hidden


@pytest.mark.parametrize("junk", [b"", b"<firstrun", b"{}", b"<other/>",
                                  b'<!DOCTYPE x [<!ENTITY a "b">]><firstrun hidden="false">&a;</firstrun>'])
def test_a_broken_file_reads_as_hidden_and_is_left_alone(junk):
    f().write_bytes(junk)
    assert firstrun.load().hidden and not firstrun.load().shows
    assert firstrun.mark("name") is False and not firstrun.set_hidden(False)
    assert f().read_bytes() == junk


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="symbolic links")
def test_a_link_is_never_followed(env):
    target = env / "elsewhere.xml"
    target.write_text('<firstrun hidden="false"/>')
    f().symlink_to(target)
    assert firstrun.load().hidden
    assert firstrun.mark("name") is False and firstrun.install_first() is False
    assert target.read_text() == '<firstrun hidden="false"/>'


def test_a_write_that_fails_returns_false_and_raises_nothing(monkeypatch):
    def boom(*a, **k):
        raise PermissionError("read-only")
    monkeypatch.setattr(firstrun.pairing, "_write_atomic", boom)
    assert firstrun.install_first() is False
    assert firstrun.set_hidden(True) is False
    assert firstrun.load().hidden


def test_the_file_is_in_the_state_folder_with_the_state_mode():
    firstrun.install_first()
    assert f().parent == config.paths().state
    if os.name != "nt":
        assert (f().stat().st_mode & 0o777) == 0o644
