#!/usr/bin/env bash
# Installed as /usr/local/bin/filament-kit: the old name of the command (06 section 2). It prints one line on
# standard error, then runs `spoolwarden` with the same arguments, standard input, standard output and exit code.
# The line is printed on every run, also with --quiet and --json. Kept for at least two minor releases; from the
# release before its removal the line ends "goes away in <version>." instead of "will be removed."
printf 'Note: filament-kit is now called spoolwarden; the old name will be removed.\n' >&2
exec /usr/local/bin/spoolwarden "$@"
