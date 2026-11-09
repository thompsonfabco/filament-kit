"""What tools/testenv.sh needs to know about a pytest run, from pytest itself rather than from its printed text.

As a plugin (`-p fk_outcomes --fk-outcomes=FILE`), the run's main process writes one line per report and per collection: under xdist
it also sees the workers' reports. As a program, it answers from that file:

    fk_outcomes.py complete FILE   exit 0 if the run reached every test it collected, else say what is missing
    fk_outcomes.py failed FILE     the ids that failed, one per line
    fk_outcomes.py passed FILE     the ids that passed: the test itself ran and no phase of it failed
"""
import sys


def pytest_addoption(parser):
    parser.addoption("--fk-outcomes", default=None, help="write this run's outcomes to this file (tools/testenv.sh)")


def pytest_configure(config):
    path = config.getoption("--fk-outcomes")
    if path and not hasattr(config, "workerinput"):
        config.pluginmanager.register(_Writer(path), "fk_outcomes_writer")


class _Writer:
    def __init__(self, path):
        self._file = open(path, "a", encoding="utf-8")

    def _line(self, *fields):
        # one write each, flushed: a main process killed half way leaves what it had, and that reads as incomplete
        self._file.write("\t".join(fields) + "\n")
        self._file.flush()

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self._line("failed", report.nodeid)
        elif report.when == "call" and report.passed:
            self._line("passed", report.nodeid)
        else:
            self._line("other", report.nodeid)

    def pytest_collectreport(self, report):
        if report.failed:
            self._line("collect-error", report.nodeid)

    def pytest_collection_finish(self, session):
        self._line("collected", str(len(session.items)))

    def pytest_xdist_node_collection_finished(self, node, ids):
        self._line("collected", str(len(ids)))


# xdist is optional for the plugin (a run with -n 0 has none), so its hook mustn't be a required one.
_Writer.pytest_xdist_node_collection_finished.optionalhook = True


def _read(path):
    failed, passed, reached, collected, collect_errors = {}, {}, {}, 0, 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            kind, _, value = line.rstrip("\n").partition("\t")
            if kind == "collected":
                collected = max(collected, int(value))
            elif kind == "collect-error":
                collect_errors += 1
            else:
                reached[value] = True
                if kind == "failed":
                    failed[value] = True
                elif kind == "passed":
                    passed[value] = True
    return failed, passed, reached, collected, collect_errors


def main(argv):
    command, path = argv
    try:
        failed, passed, reached, collected, collect_errors = _read(path)
    except OSError:
        print("no outcomes were written")
        return 1
    if command == "complete":
        if collect_errors:
            print(f"{collect_errors} could not be collected")
            return 1
        if not collected or len(reached) < collected:
            print(f"stopped early, {len(reached)} of {collected} tests reached")
            return 1
        return 0
    if command == "failed":
        print("\n".join(failed))
    elif command == "passed":
        print("\n".join(t for t in passed if t not in failed))
    else:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
