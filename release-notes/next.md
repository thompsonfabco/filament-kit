# Next release: notes in progress

This file collects what the next release changes for you, and the release's text is taken from here.

## Storage locations

Where your spools are kept is now one ordered list of **storage locations** that you edit, instead of five fixed
settings. Each location has a name and a type: **Bulk storage** (a shelf, rack or drawer, with an optional spool limit)
or **Individual containers** (boxes or bags that hold one spool each; the Hub numbers them, for example `Dry box 01`).
It is filled automatically with nothing, any material or the materials you name, and it can be overflow. One overflow
location is the default overflow, and one Bulk storage location takes the sealed spools.

A spool you add without a location goes to the sealed location when it is still sealed. Otherwise it goes to the first
place for its material that has room, then to the first place that takes any material, then to an overflow location.
With PLA rack 1 limited to 20 spools and PLA rack 2 behind it, the 21st PLA spool goes to rack 2. Choosing a place by
hand still works when it is full.

**What happens when you upgrade.** The first time the Hub starts, it builds the list from your old settings (Locations,
PLA rack, Box location prefix, Number of storage boxes, Overflow location), so every new spool is placed where it was
before. Nothing is lost, and spools already stored keep their place. The old settings stay in the configuration file and
are no longer read. The list is saved in `/var/lib/filament-kit/storage.xml`, which backups include. If the old
settings gave one name two jobs, the Hub page and `sudo spoolwarden locations` say **Storage locations were converted.
Check them.** Look at the list and save it, and the notice goes. If the Hub cannot save or read the list, it keeps
running and says so as a **Needs a look** row in `spoolwarden status` and on the Overview.

**Where to edit it.** On the Hub page, **Settings**, **Storage locations**: add, edit, reorder and remove locations,
mark the default overflow and the sealed location, and see where a new spool of each material would go before you save.
At a Terminal, `sudo spoolwarden locations` lists the list and has `add`, `edit`, `move`, `remove`, `default-overflow`
and `sealed`; `sudo spoolwarden config` has the same screen. `config set` no longer takes the old settings and points to
`locations`. Renaming a location renames it on the spools stored there.

**In the apps.** The phone web app and the Android app show how full each place is in the **Location** choice and in
**Move**, mark a full place as **Full** (it can still be chosen), and after a preview say where a spool on **Automatic**
would go and why. The list itself is edited on the Hub page or the command line.

## The command is `spoolwarden`

- **The command is now `spoolwarden`.** Install and update put `spoolwarden` where `filament-kit` was; `spoolwarden --version` prints `Spoolwarden <version>`, and the help, messages and Fix lines name it. `filament-kit` still works for a time: it runs `spoolwarden` with the same arguments, input, output and exit code, and prints one line on standard error saying the name changed.
