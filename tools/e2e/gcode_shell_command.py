# Test stand-in for the gcode_shell_command Klipper extra (KIAUH's), used only by tools/e2e/klipper.sh: it is copied
# into the scratch Klipper's klippy/extras. It behaves like the real one where the printer pack depends on it:
# `command` is split with shlex at config time, RUN_SHELL_COMMAND CMD=<name> PARAMS="..." splits PARAMS with
# shlex.split OUTSIDE any try block (so a bad quote raises inside the command handler, which Klipper turns into a
# shutdown, as on a real printer), the process runs with a timeout while the reactor keeps running, and its output is
# sent to the console line by line.
import os
import shlex
import subprocess


class ShellCommand:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.command = shlex.split(os.path.expanduser(config.get("command")))
        self.timeout = config.getfloat("timeout", 2., above=0.)
        self.verbose = config.getboolean("verbose", True)
        self.gcode.register_mux_command("RUN_SHELL_COMMAND", "CMD", self.name, self.cmd_RUN_SHELL_COMMAND,
                                        desc="Run a linux command or script")

    def cmd_RUN_SHELL_COMMAND(self, params):
        args = shlex.split(params.get("PARAMS", ""))       # deliberately outside the try, like the real extra
        reactor = self.printer.get_reactor()
        try:
            proc = subprocess.Popen(self.command + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except Exception:
            self.gcode.respond_info("shell command %s: failed to start" % self.name)
            return
        end = reactor.monotonic() + self.timeout
        while proc.poll() is None and reactor.monotonic() < end:
            reactor.pause(reactor.monotonic() + .05)
        if proc.poll() is None:
            proc.kill()
            self.gcode.respond_info("shell command %s: timed out" % self.name)
            return
        out = proc.stdout.read().decode("utf-8", "replace")
        if self.verbose:
            for line in out.splitlines():
                self.gcode.respond_info(line)


def load_config_prefix(config):
    return ShellCommand(config)
