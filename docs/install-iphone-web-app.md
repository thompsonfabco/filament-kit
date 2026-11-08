# Use the web app on an iPhone

There is no filament-kit app for iPhone. Instead, the server can run a **phone web app** that works in Safari,
and you can put it on your home screen so it opens like an app. It also works in any other phone browser,
Android included.

The web app does most of what the Android app does:

- **Add spools**: pick a filament you already have or type a new one in, check it (a dry run), then add it.
  With AI label reading on at the server, you can also photograph labels.
- **Open spool**: link a tag you tapped on a reader (the intake station or a printer's reader) to a spool and
  record its weight and place. The iPhone itself does not read the tag.
- **Presets**: see which filaments still need a slicer preset, and build presets.
- **Printers** (when the `printers` module is on): live status, the camera, pause, resume and stop, the
  chamber light, what is in each AMS slot and the filament usage log.

It only works **on your home network**. Away from home it says "Spool intake only works on the home network."
There is no sign-in: anyone on your home Wi-Fi can use it.

> **This takes more setup than the Android app.** The web app is part of the `web` module, and Safari only
> reaches it over `https://`. So the server needs an https address and a web server (nginx) in front of it.
> There are two ways to get one, below. Neither has been tried on a real iPhone yet; see [Known gaps](known-gaps.md).

## What you need

- The **filament-kit server installed and running**: [Install the server](install-server.md).
- An **iPhone with Safari**, on the same Wi-Fi network as the server.
- Access to the server's Terminal.
- For [way B](#way-b-a-public-name-with-a-real-certificate) only: a domain name you control, and access to your
  router's port forwarding.

## Choose a way

| | Way A: home only | Way B: a public name |
|---|---|---|
| Address | `https://<computer name>.local/filament` | `https://filament.example.com/filament` (your own name) |
| What you need | nothing extra | a domain name, ports 80 and 443 forwarded to the server |
| Safari | warns about the certificate (you accept it once) | no warnings |
| Also gives you | | the Claude connector from outside |

## Way A: home only

1. On the server, find the computer's name:

   ```bash
   hostname
   ```

   Say it prints `my-server`. Your address is then `https://my-server.local/filament`.

2. Open the settings menu:

   ```bash
   sudo filament-kit config
   ```

3. Type `6` and press Enter (**Modules**). A checklist of modules appears. Move with the arrow keys and press Space
   on **web** and on **remote** to tick them. Then press Enter to apply.
4. When it asks `web needs its public https address`, type your address, for example
   `https://my-server.local/filament`, and press Enter.
5. Back at the settings menu, type `0` and press Enter to save. The kit installs nginx and sets it up. Among its
   output it prints a list of firewall and router rules: for home-only use you can **ignore them**. Do not run
   `sudo filament-kit remote issue`: that only works with a public name.
6. Check it:

   ```bash
   sudo filament-kit web status
   ```

   You should see `OK   web module is on`, `OK   public URL ...` and `OK   web unit answers`. It also shows
   `--   sign-in passphrase not set`. That passphrase is only for the Claude connector, not for the phone web
   app, so you can ignore it (or set one with `sudo filament-kit web passphrase`).

nginx now serves the web app with a certificate the server made itself. Safari doesn't know that certificate, so
it warns the first time (see below).

## Way B: a public name with a real certificate

Use this if you have a domain name, or want the Claude connector to reach your server from the internet.

1. Pick a name such as `filament.example.com`, and in your domain's DNS point it at your home's public IP address.
2. **At home, the same name must lead to the server.** Many routers handle this by themselves ("NAT loopback").
   If yours doesn't, add a local DNS entry for the name on your router pointing at the server's home IP address.
3. Do steps 2 to 5 of way A, with the address `https://filament.example.com/filament`.
4. Print the rules you need and set them up on your router and firewall:

   ```bash
   sudo filament-kit remote firewall
   ```

   They are: port 443 to the server, and port 80 to the server while a certificate is issued.
5. Get the certificate:

   ```bash
   sudo filament-kit remote issue
   ```

   From then on the certificate renews itself.

More about this, and keeping port 80 closed most of the time: [user guide, Remote access](user-guide.md#remote-access).

## Open it in Safari and add it to the home screen

1. On the iPhone, connect to your home Wi-Fi.
2. Open **Safari** and type your address followed by `/intake`, for example
   `https://my-server.local/filament/intake`.
3. **Way A only:** Safari says **This Connection Is Not Private**. Tap **Show Details**, then
   **visit this website**, and confirm with **Visit Website**.
4. The web app opens on **Add spools**, with the tabs **Add spools**, **Open spool**, **Presets** and (with the
   printers module) **Printers** at the top.
5. Tap the **Share** button (the square with an arrow), scroll down and tap **Add to Home Screen**.
6. The name is **Spools**. Change it if you like and tap **Add**.

A **Spools** icon is now on your home screen. It opens the web app full screen. (Way A: whether a home-screen web app
keeps working with an accepted self-signed certificate has not been tried on a real iPhone; see
[Known gaps](known-gaps.md).)

## Add a spool

1. In **Add spools**, under **Add by hand**, search for a filament you already have (brand, colour, material) and
   tap it, or tap **New filament (type it in)**.
2. Fill in the card: at least **Vendor**, **Material** and **Name (with the colour)**, then **Spools** (how
   many), **Net g** and the **Location** (**Auto** picks one for you). Tick **Still sealed** for a spool still
   in its bag.
3. Tap **Check (dry run)**. It shows what would be added and changes nothing.
4. If it looks right, tap **Add 1 spool** (or **Add 3 spools**, and so on). Any change after the check needs a new
   check.

**From label photos** (**Take or choose photos**) only appears when AI label reading (the `ai_intake` module)
is on at the server.

## Load and unload a spool from the Printers tab (v0.4.0)

The **Printers** tab (it needs the `printers` module) shows each printer live: status, camera, controls and the
filament in each slot.

**Load.** Next to a slot, tap **Load**. A picker opens: find the spool and tap it. The page first shows the plan
and sends nothing: the filament preset it will set, the nozzle, and any spool that goes back to its old place.
Check it and tap **Load**, or **Cancel**. The message then says **Loaded into** the slot (the printer confirmed) or
**Sent to** the slot (sent, not yet confirmed by the printer). If the plan can't be made, the page says why and
does nothing.

**Unload.** Next to a slot with a spool, tap **Unload**. It asks, for example, "Unload PETG Grey from AMS1-2? It
goes back to Shelf A." Tap **OK**. Only your inventory changes; the printer's own slot setting stays as it is.

The same rules as the Android app apply: for example, while a print runs, the slot that feeds the job is refused.
See [Using the Android app](android-app.md#load-and-unload-a-spool). The tab also has the filament usage with undo,
re-mapping slots and optional notifications.

## Common problems

- **"Spool intake only works on the home network"** while you are at home:
  - Check that the iPhone is on your home Wi-Fi, not mobile data.
  - The kit counts addresses starting with `192.168.` and `10.` as home. If your home network uses addresses
    starting with `172.16.` to `172.31.`, add your network to `/etc/filament-kit/config.json` under `"web"`, for
    example `"lan": ["172.20.0.0/16"]`, then run `sudo filament-kit modules apply`. (On iPhone: Settings → Wi-Fi →
    the ⓘ next to your network shows the iPhone's address.)
  - Way B: if your router doesn't do NAT loopback, the phone goes out to the internet and back, and looks like it
    is away from home. Add the local DNS entry from way B, step 2.
- **Safari can't find the server** (way A): `.local` names need the iPhone and the server on the same network.
  Check `sudo filament-kit status` on the server. If Ubuntu's firewall (`ufw`) is on, allow
  `sudo ufw allow 443/tcp` and `sudo ufw allow 5353/udp`.
- **`web needs web.public_url set`** when you run `sudo filament-kit modules enable web` without a terminal: it can
  only ask for the address at a terminal. Run it in a Terminal, or use `sudo filament-kit config` → **6) Modules**
  as above.
- **The certificate warning comes back** (way A): each time the server's certificate changes (after
  reinstalling), Safari asks again. Accept it again. The placeholder certificate lasts 825 days. Running
  `sudo filament-kit modules apply` makes a new one within 30 days of its end (`sudo filament-kit web status` warns
  before that), and Safari asks you to accept it again.
- **The page says "This device reached the server over IPv6"**: the web address answers only the ranges in `web.lan`,
  and none of them is an IPv6 range by default. On the server, run `ip -6 addr show scope global`: an address such as
  `2001:db8:1234:5678::abcd/64` has the prefix `2001:db8:1234:5678::/64` (the first four groups). Add that prefix to
  `web.lan` in `/etc/filament-kit/config.json`, next to the existing ranges, then run `sudo filament-kit modules
  apply`. A home network's IPv6 prefix can change when your provider changes it. The setup page is IPv4 only.
- **Printer camera doesn't play**: the camera needs the `printers` module and a printer added in the app or in
  `sudo filament-kit config` → **5) Printers**.

More about the web app and the Claude connector: [user guide, Claude connector and phone web app](user-guide.md#claude-connector-and-phone-web-app).
