# Use the web app on an iPhone

There is no Spoolwarden app for iPhone. Instead, the Hub can run a **web app** that works in Safari,
and you can put it on your home screen so it opens like an app. It also works in any other phone browser,
Android included.

The web app does most of what the app (Android) does:

- **Add spools**: pick a filament you already have or type a new one in, check it (a preview, nothing is saved yet), then add it.
  With the Label Reader's Cloud engine on at the Hub, you can also photograph labels.
- **Open spool**: link a tag you tapped on a reader (a Weigh Station or a Tag Reader) to a spool and
  record its weight and place. The iPhone itself does not read the tag.
- **Slicer presets**: see which filaments still need a Slicer preset, and build Slicer presets.
- **Printers** (when the Bambu Lab printers Feature is on): live status, the camera, pause, resume and stop, the
  chamber light, what is in each AMS slot and the filament usage log.

It only works **on your home network**. Away from home it says "Spoolwarden only works on the home network."
There is no sign-in: anyone on your home Wi-Fi can use it.

> **At home it needs no setup.** The Hub serves the web app itself at
> `https://<server name>.local/intake` (the Hub page's **Devices** section shows the address and a QR code; a Hub that
> kept port 8710 has `:8710` after the name).
> Safari warns once about the Hub's own certificate: accept it to go on. To avoid the warning, or to reach the
> app with a name of your own, use one of the two ways below (the `web` Feature and a web server in front). None of
> this has been tried on a real iPhone yet; see [Known gaps](known-gaps.md).

## What you need

- The **Hub installed and running**: [Install the Hub](install-server.md).
- An **iPhone with Safari**, on the same Wi-Fi network as the Hub.
- For way A or B: access to the Hub's Terminal.
- For [way B](#way-b-a-public-name-with-a-real-certificate) only: a domain name you control, and access to your
  router's port forwarding.

## Choose a way

| | The built-in address | Way A: home only, nginx | Way B: a public name |
|---|---|---|---|
| Address | `https://<server name>.local/intake` (`:8710` after the name on a Hub that kept that port) | `https://<computer name>.local/filament` | `https://filament.example.com/filament` (your own name) |
| What you need | nothing: the Hub serves it | the `web` and `remote` Features (Spoolwarden installs nginx) | a domain name, ports 80 and 443 forwarded to the Hub |
| Safari | warns about the certificate (you accept it once) | warns about the certificate (you accept it once) | no warnings |
| Also gives you | | an address without a port number | the Claude connector from outside |

Start with the built-in address. Use way A or B only to avoid the warning or to use a name of your own.

Way A and way B switch on Remote access, which needs port 443 for itself. A Hub that holds 443 (a new install where
443 was free) refuses it: `Remote access needs port 443, and the Hub is using it`. They need a Hub on another port: one that
kept 8710, or one installed with Remote access chosen, which then takes 8710.

## The built-in address: no setup

1. Open the Hub page's **Devices** section: it shows the address and a QR code. Or build it yourself: the Hub's name
   from `hostname`, for example `https://my-server.local/intake` (`https://my-server.local:8710/intake` on a Hub that kept
   port 8710).
2. Go on to [Open it in Safari](#open-it-in-safari-and-add-it-to-the-home-screen) and use that address.

## Way A: home only

1. On the Hub, find the computer's name:

   ```bash
   hostname
   ```

   Say it prints `my-server`. Your address is then `https://my-server.local/filament`.

2. Open the Features checklist:

   ```bash
   sudo spoolwarden features menu
   ```

3. A checklist of Features appears. Move with the arrow keys and press Space
   on **Web access** and on **Remote access** to tick them. Then press `s` to apply.
4. When it asks `web needs its public https address`, type your address, for example
   `https://my-server.local/filament`, and press Enter.
5. Spoolwarden installs nginx and sets it up. Among its
   output it prints a list of firewall and router rules: for home-only use you can **ignore them**. Do not run
   `sudo spoolwarden remote get-certificate`: that only works with a public name.
6. Check it:

   ```bash
   sudo spoolwarden web status
   ```

   You should see `OK   web module is on`, `OK   public URL ...` and `OK   web unit answers`. It also shows
   `--   sign-in passphrase not set`. That passphrase is only for the Claude connector, not for the web
   app, so you can ignore it (or set one with `sudo spoolwarden web passphrase`).

nginx now serves the web app with a certificate the Hub made itself. Safari doesn't know that certificate, so
it warns the first time (see below).

## Way B: a public name with a real certificate

Use this if you have a domain name, or want the Claude connector to reach your Hub from the internet.

1. Pick a name such as `filament.example.com`, and in your domain's DNS point it at your home's public IP address.
2. **At home, the same name must lead to the Hub.** Many routers handle this by themselves ("NAT loopback").
   If yours doesn't, add a local DNS entry for the name on your router pointing at the Hub's home IP address.
3. Do steps 2 to 5 of way A, with the address `https://filament.example.com/filament`.
4. Print the rules you need and set them up on your router and firewall:

   ```bash
   sudo spoolwarden remote firewall
   ```

   They are: port 443 to the Hub, and port 80 to the Hub while a certificate is issued.
5. Get the certificate:

   ```bash
      sudo spoolwarden remote get-certificate
   ```

   From then on the certificate renews itself.

More about this, and keeping port 80 closed most of the time: [user guide, Remote access](user-guide.md#remote-access).

## Open it in Safari and add it to the home screen

1. On the iPhone, connect to your home Wi-Fi.
2. Open **Safari** and type your address. The built-in address already ends in `/intake`; for way A or B add `/intake`
   to your address, for example `https://my-server.local/filament/intake`.
3. **The built-in address and way A:** Safari says **This Connection Is Not Private**. Tap **Show Details**, then
   **visit this website**, and confirm with **Visit Website**.
4. The web app opens on **Add spools**, with the tabs **Add spools**, **Open spool**, **Slicer presets** and (with the
   Bambu Lab printers Feature) **Printers** at the top.
5. Tap the **Share** button (the square with an arrow), scroll down and tap **Add to Home Screen**.
6. The name is **Spools**. Change it if you like and tap **Add**.

A **Spools** icon is now on your home screen. It opens the web app full screen. (Way A: whether a home-screen web app
keeps working with an accepted self-signed certificate has not been tried on a real iPhone; see
[Known gaps](known-gaps.md).)

## Add a spool

1. In **Add spools**, under **Add by hand**, search for a filament you already have (brand, colour, material) and
   tap it, or tap **New filament (type it in)**.
2. Fill in the card: at least **Vendor**, **Material** and **Name (with the colour)**, then **Spools** (how
   many), **Net g** and the **Location** (**Automatic** picks one for you; the list shows how full each place is).
   Tick **Still sealed** for a spool still in its bag.
3. Tap **Check**. It shows what would be added and changes nothing (a preview). Under **Location** it says where a
   spool on **Automatic** would go, and why.
4. If it looks right, tap **Add 1 spool** (or **Add 3 spools**, and so on). Any change after the check needs a new
   check.

**From label photos** (**Take or choose photos**) only appears when the Label Reader's Cloud engine (the `ai_intake` Feature)
is on at the Hub.

## Load and unload a spool from the Printers tab (v0.4.0)

The **Printers** tab (it needs the Bambu Lab printers Feature) shows each printer live: status, camera, controls and the
filament in each slot.

**Load.** Next to a slot, tap **Load**. A picker opens: find the spool and tap it. The page first shows the plan
and sends nothing: the filament preset it will set, the nozzle, and any spool that goes back to its old place.
Check it and tap **Load**, or **Cancel**. The message then says **Loaded into** the slot (the printer confirmed) or
**Sent to** the slot (sent, not yet confirmed by the printer). If the plan can't be made, the page says why and
does nothing.

**Unload.** Next to a slot with a spool, tap **Unload**. It asks, for example, "Unload PETG Grey from AMS1-2? It
goes back to Shelf A." Tap **OK**. Only your inventory changes; the printer's own slot setting stays as it is.

The same rules as the app (Android) apply: for example, while a print runs, the slot that feeds the job is refused.
See [Using the app](android-app.md#load-and-unload-a-spool). The tab also has the filament usage with undo and
re-mapping slots.

## Alerts

The Hub writes down what happens (a print runs out of filament, pauses or fails, a printer reports a problem, storage is
almost full, a spool is running low, a device stops answering) and turns the kinds you have switched on into alerts. Which kinds are on, and
the limits, are set on the Hub: [Alerts in the user guide](user-guide.md#alerts).

- **While the web app is open**, an alert shows as a banner at the top of the page (at most two, then **<n> more alerts**)
  and as a short message when it arrives. The page asks the Hub every 10 seconds and stops asking while it is hidden, so
  an alert that came meanwhile appears when you open it again. In **More**, **Settings**, **Recent alerts** lists what is
  happening now and the alerts of the last 7 days. A **Running low (n)** button appears in the spool search when spools are running low; it lists them.
- **With the web app closed**, the phone gets a notification only when Web Push is on. It is off by default, and it works only
  at the `web` Feature's address (way A or B), not at the built-in address. The Hub needs the optional push package and the
  web service needs a way out to the browsers' push services; the steps are in the
  [user guide](user-guide.md#claude-connector-and-phone-web-app).
- **Then, on the iPhone, put the web app on the Home Screen** (as above): in Safari the page says **This browser cannot
  receive alerts. Alerts on iPhone work only from the Home Screen.** and offers **Add to Home Screen**. Open it from the
  Home Screen, go to **More**, **Settings**, **Alerts on this phone**, switch on **Notify this phone** and allow notifications
  when iOS asks. It then says **On: this phone gets alerts.** If notifications are blocked it says **Notifications are
  blocked for this site. Allow them in the phone's settings.**
- **Send a test alert** (on the same page) sends one notification to the phones that switched this on, to check that it works. It
  waits 30 seconds between tests. If the push service cannot be reached, the message says so.

## Common problems

- **"Spoolwarden only works on the home network"** while you are at home:
  - Check that the iPhone is on your home Wi-Fi, not mobile data.
  - Spoolwarden counts addresses starting with `192.168.` and `10.` as home. If your home network uses addresses
    starting with `172.16.` to `172.31.`, add your network to `/etc/filament-kit/config.json` under `"web"`, for
    example `"lan": ["172.20.0.0/16"]`, then run `sudo spoolwarden features apply`. (On iPhone: Settings → Wi-Fi →
    the ⓘ next to your network shows the iPhone's address.)
  - Way B: if your router doesn't do NAT loopback, the phone goes out to the internet and back, and looks like it
    is away from home. Add the local DNS entry from way B, step 2.
- **Safari can't find the Hub** (way A): `.local` names need the iPhone and the Hub on the same network.
  Check `sudo spoolwarden status` on the Hub. If Ubuntu's firewall (`ufw`) is on, allow
  `sudo ufw allow 443/tcp` and `sudo ufw allow 5353/udp`.
- **`web needs web.public_url set`** when you run `sudo spoolwarden features on web` without a terminal: it can
  only ask for the address at a terminal. Run it in a Terminal, or use `sudo spoolwarden features menu`
  as above.
- **The certificate warning comes back** (way A): each time the Hub's certificate changes (after
  reinstalling), Safari asks again. Accept it again. The placeholder certificate lasts 825 days. Running
  `sudo spoolwarden features apply` makes a new one within 30 days of its end (`sudo spoolwarden web status` warns
  before that), and Safari asks you to accept it again.
- **The page says `This device reached the server over IPv6`**: the web address answers only the ranges in `web.lan`,
  and none of them is an IPv6 range by default. Add your home network's IPv6 prefix:
  [The home network ranges](user-guide.md#the-home-network-ranges-weblan). The Hub page is IPv4 only.
- **Printer camera doesn't play**: the camera needs the Bambu Lab printers Feature and a printer added in the app or with
  `sudo spoolwarden printer add`.

More about the web app and the Claude connector: [user guide, Claude connector and web app](user-guide.md#claude-connector-and-phone-web-app).
