"""bridge.family: the dispatcher routes each printer to its family by the registry's `family`."""
import pytest

from filament_kit.bridge import family, registry


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))


class Fake:
    def __init__(self, tag):
        self.tag, self.synced, self.started, self.stopped = tag, 0, 0, 0

    def state(self, pid):
        return f"{self.tag}:{pid}"

    def summary(self, pid):
        return {"from": self.tag}

    def status(self, pid):
        return {"from": self.tag}

    def command(self, pid, action):
        return {"ok": True, "reply": {"by": self.tag}}

    def wait_settled(self, pid, timeout):
        return self.state(pid)

    def sync(self):
        self.synced += 1

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def wait_report(self, *a):
        return "bambu-only"


def _two():
    registry.upsert(registry.Printer("S1", "H2D", configured=True))
    k = registry.add_klipper("SV08 MAX", "sv08.home.arpa")
    return family.Printers(bambu=Fake("b"), klipper=Fake("k")), k.serial


def test_routes_by_family():
    p, kid = _two()
    assert p.state("S1") == "b:S1"
    assert p.state(kid) == f"k:{kid}"
    assert p.command(kid, "pause")["reply"]["by"] == "k"
    assert p.status("S1") == {"from": "b"}
    assert p.family_of(kid) == "klipper" and p.family_of("S1") == "bambu"


def test_unknown_printer_is_bambu():
    p, _ = _two()
    assert p.family_of("nope") == "bambu"
    assert p.state("nope") == "b:nope"


def test_unknown_attr_goes_to_bambu():
    p, _ = _two()
    assert p.wait_report("S1", None, 0) == "bambu-only"


def test_sync_start_stop_reach_both():
    p, _ = _two()
    p.sync()
    p.start()
    p.stop()
    assert (p.bambu.synced, p.klipper.synced, p.bambu.started, p.klipper.stopped) == (1, 1, 1, 1)


def test_klipper_module_off():
    registry.add_klipper("SV08 MAX", "h")
    p = family.Printers(bambu=Fake("b"), klipper=None)
    assert p.state("sv08-max") == "not_configured"
    assert p.summary("sv08-max") is None and p.status("sv08-max") is None
    with pytest.raises(family.ModuleOff):
        p.command("sv08-max", "pause")


def test_bambu_module_off():
    registry.upsert(registry.Printer("S1", configured=True))
    p = family.Printers(bambu=None, klipper=Fake("k"))
    assert p.state("S1") == "not_configured"


def test_klipper_entry_ids():
    assert family.is_klipper_entry("k-abc") and not family.is_klipper_entry("abc")


def test_wait_settled_routes_and_reads_not_configured_when_the_module_is_off():
    p, kid = _two()
    assert p.wait_settled(kid, 1) == f"k:{kid}" and p.wait_settled("S1", 1) == "b:S1"
    assert family.Printers(bambu=Fake("b"), klipper=None).wait_settled(kid, 1) == "not_configured"


def test_bambu_command_with_the_module_off_raises():
    registry.upsert(registry.Printer("S1", configured=True))
    p = family.Printers(bambu=None, klipper=Fake("k"))
    with pytest.raises(family.ModuleOff) as e:
        p.command("S1", "pause")
    assert e.value.family == "bambu"
    assert p.summary("S1") is None and p.status("S1") is None
