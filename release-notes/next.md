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

## Alerts

The Hub now writes down what happens (a print starts, pauses, runs out of filament, fails or finishes; a printer reports an
error; a spool is added, moved or runs low; the Hub's disk fills; a device stops answering) and turns the kinds you want into
**alerts**. Eight kinds exist: **Filament ran out**, **Print paused**, **Print failed or stopped**, **Printer error**,
**Storage almost full** and **Spool running low** are on at the start; **Print finished** and **Device stopped answering**
are off.

**Where they show.** The phone web app and the Android app show an alert as a banner at the top (at most two, then **<n> more
alerts**), with a button to the place that deals with it and **Dismiss**. **Recent alerts** lists what is happening now and the
alerts of the last 7 days. In the web app it is under **More**, **Settings**; in the Android app, under **Settings**,
**Alerts**.

**On the Hub page.** The Hub page shows the same banners at the top of the page. **Settings**, **Alerts** has the eight
switches, a switch to limit **Spool running low** to the last spool of a filament, **Running low under** and **Storage
warning at**; **Save alerts** saves them with the setup code, like the other settings. Under **On this device**, **Recent
alerts** opens the list and **Send a test alert** sends one to that browser. The switch **Notifications in this browser**
(off until you turn it on; the browser asks to allow notifications) shows each new alert as a notification while a Hub page
tab is open in that browser; a tab in the background can be up to a minute late, and with every tab closed nothing arrives.

**On the phone with the app closed.** In the Android app, **Settings**, **Alerts**, the switch **Alerts on this phone**
(off until you turn it on) makes the app watch the Hub and notify you for each alert, with Android's small permanent
notification **Watching the Hub for alerts**. It needs the phone to reach the Hub, so away from home nothing arrives until
it does. In the phone web app, notifications with the app closed use Web Push, which stays off until you set
`"web": {"push": true}` and install `filament-kit[push]`; it works at the `web` Feature's address, and on an iPhone from the
Home Screen. **Send a test alert** is on the same pages, and `sudo spoolwarden alerts test` sends one to every device that
asks within a minute.

**Running low and storage.** An opened spool at or under 150 g is running low (a spool that is the last one of its filament is
marked **Last one**). The Hub's disk is warned about at 85 % used and counts as full at 95 % used or under 1 GB free.
`spoolwarden status` and the Hub page's Overview show the disk (`Storage: 41 GB free of 117 GB (65 % used)`) and, while some
spools are running low, a note. The web app has a **Running low (n)** button in the spool search and the Android app one on its
home screen. On the Hub page, the Overview has a **Running low** card while a spool is running low (**Show all <n>** opens
every spool), and a Storage row that needs a look has **Show storage use**, which opens a **Storage use** panel with the
disks and the space the Hub's backups, photos, events and logs take.

**The commands.** `spoolwarden events [--since ID|TIME] [--kind PREFIX] [--follow]` lists the Hub's events.
`spoolwarden alerts` shows the switches and limits; `sudo spoolwarden alerts set <type> on|off`, `alerts set running-low
<grams>` and `alerts set storage-warning <percent>` change them; `sudo spoolwarden alerts test` sends a test alert.
`spoolwarden spools low` lists the spools running low, least filament first.

**What happens when you upgrade.** Nothing to do. Alerts work once the Hub is updated, with the defaults above. The
events and the alert settings are kept in `/var/lib/filament-kit` (`events` and `alerts.xml`), which backups include.

## The Hub's address and first run

**A new install puts the Hub on port 443**, so its address has no port: `https://my-server.local/setup` instead of
`https://my-server.local:8710/setup`. If 443 is in use (another web server, or Remote access, which needs 443 for itself), the
installer asks for another port at a Terminal and offers 8710; without a Terminal, or with Guided Setup, it takes 8710 and says
so. The Android app and Slicer Sync take a typed address without a port: they try 443 and then 8710, and use the one that
answers.

**Guided Setup.** A first install at a Terminal now begins with **Finish setting up in your browser (Guided Setup)?**
Yes installs the Hub with the usual choices, asks nothing more and ends with the Hub's address and the setup code. No asks the
questions in the Terminal, as before, and is the way to install only a Weigh Station. Giving `--mode`, `--modules`, `--set` or
`--hub` skips the question.

**The Weigh Station serves HTTPS.** A Weigh Station now answers over HTTPS, with a certificate it makes for itself. Each
time it starts, a paired Weigh Station tells the Hub its certificate, its port and its version, so the Hub learns them by
itself and accepts only that certificate from it; a changed certificate is refused, never replaced by plain HTTP. A first
install of a Weigh Station on a computer of its own takes port 443 when that is free; when it is in use, the installer at a
Terminal asks `Port for the Weigh Station [5003]:`. Beside a Hub it takes 5003 without asking. A Weigh Station that is
not updated yet tells the Hub no certificate, and the Hub keeps calling it over plain HTTP.

**A Label Reader on another computer.** An `http://` address keeps working as before. For an `https://` address the Hub
keeps the reader's certificate from the first time it reaches the reader and accepts no other from that address.

**What happens when you upgrade.** Nothing to do. An existing Hub keeps the port it has, 8710 for almost every Hub, and so
do its phones, Slicer Sync and the addresses you use: `https://my-server.local:8710/setup` keeps working. An update never moves
a Hub. When `ufw` is on, the installer prints the line to open the Hub's port, for example `sudo ufw allow 443/tcp`; it
does not change the firewall.

## The command is `spoolwarden`

- **The command is now `spoolwarden`.** Install and update put `spoolwarden` where `filament-kit` was; `spoolwarden --version` prints `Spoolwarden <version>`, and the help, messages and Fix lines name it. `filament-kit` still works for a time: it runs `spoolwarden` with the same arguments, input, output and exit code, and prints one line on standard error saying the name changed.
