# Install the Android app

The filament-kit app is how you add spools, look them up, load them into printer slots and see your printers
from an Android phone. It talks only to your own filament-kit server at home.

> **Beta.** The app is not in the Google Play Store or F-Droid. It comes as a file, `filament-kit.apk`, on the
> project's GitHub Releases page. See [Known gaps](known-gaps.md).

## What you need

- An **Android phone or tablet with Android 10 or newer**.
- The **filament-kit server installed and running** on your home network: [Install the server](install-server.md).
- The phone on the **same Wi-Fi network** as the server.
- Access to the server's Terminal, to show the pairing code (`sudo filament-kit pair`).
- Optional: a phone with **NFC**, to read spool tags. Turn NFC on in the phone's settings; the app asks for no
  permission for it. The app works without NFC, and without a camera (pair by typing the code instead).

## 1. Download the app

Use either way:

- **From GitHub:** on the phone, open the project's GitHub **Releases** page in Chrome and tap
  `filament-kit.apk` under **Assets** of the newest release.
- **From your server:** a server installed from a release also has the app. On the phone, open
  `https://<computer name>.local:8710/app.apk` (for example `https://my-server.local:8710/app.apk`). Chrome warns
  that the connection is not private, because the server uses its own certificate. Tap **Advanced**, then
  **Proceed**. The download itself is the same file as on GitHub.

Chrome may say the file can be harmful. Tap **Download anyway**.

## 2. Install it

1. Open the downloaded file: tap the notification, or open **Files** → **Downloads** → `filament-kit.apk`.
2. Android asks to allow apps from this source. Tap **Settings**, turn on **Allow from this source** for Chrome
   (or Files), and go back.
3. Tap **Install**.
4. **Google Play Protect** may say it doesn't recognise the app, or offer to scan it. That happens to any app
   not from the Play Store. Choose to scan it or **Install anyway**.
5. Tap **Open**.

The words differ a little between phone brands and Android versions.

## 3. Pair the phone with your server

Pairing lets the app trust your server and lets the server know your phone. You do it once per phone.

1. **On the server**, in Terminal:

   ```bash
   sudo filament-kit pair
   ```

   It shows a QR code, the server's certificate fingerprint and a 6-digit pairing code. They are good for about
   10 minutes. (The installer showed the same at the end of the install; if that code is still fresh, use it. The server's setup page,
   `https://<computer name>.local:8710/setup`, can show a pairing code too.)

2. **On the phone**, the app opens on **Pair with your server**. It asks for each permission only when it first
   needs it, not at the start:
   - On **Android 17 or newer**, the first time the app looks for your server it asks for **local network
     access**. Tap **Allow**. Without it, the app can't find or reach your server. If you said no, the app shows
     **Allow** again; if Android no longer asks, tap **Open app settings** and allow it there.
3. Tap **Scan QR code** and allow the camera when asked. Point it at the QR code in the Terminal. That's it: the
   app opens its home screen. **Keep the white border around the QR code:** scan it from the whole Terminal
   window, and don't crop it or zoom in so far that the border is cut off. (`sudo filament-kit pair` draws the code
   with its own white background, so a dark Terminal is fine.)

**If the camera can't read the QR code** (a small or blurry Terminal window helps neither):

1. Under **Servers found on this network**, tap your server: it goes straight to the fingerprint check. If it's not
   listed, tap **Enter address** and type the computer's name with `.local` (for example `my-server.local`) or its IP
   address. Leave **Port** at 8710.
2. The app shows **Check the server's fingerprint** with two groups left blank. Find the fingerprint shown with the
   pairing code (in the Terminal, or on the server's setup page) and type the two missing groups. If they are the
   same, tap **Continue**. If they differ, tap **It does not match** and stop: something else is answering at that
   address.
3. Under **Enter the pairing code**, type the 6-digit code.

To pair another phone, run `sudo filament-kit pair` again: each code works once.

## What you see after pairing

The home screen shows the buttons **Add spool**, **Add profile**, **Search**, **Printers** and **Settings**.
**Add from label photos** only appears when AI label reading (the `ai_intake` module) is on at the server.
**Settings** shows the server and its fingerprint and has **Pair again** and **Forget server**.

## Updates

The app updates itself from your server. When the server has a newer app (after `sudo filament-kit update`),
the home screen shows **Update available**. Tap **Tap to install**. The first time, Android asks to let
filament-kit install apps: allow it, go back and tap **Tap to install** again.

### Update refused

If the app's own update says **Don't install this update** and you did not build the app yourself, don't uninstall
the app. A release update is always signed like the app you already have, so a refusal means this file is not from
the same maker: check who runs the server and where its app came from. (This is different from **App not installed**
below, which happens when you install a downloaded file over an older copy signed by someone else.)

## Common problems

- **"App not installed"** (when you install a downloaded file yourself, from outside the app): the phone has an older
  copy signed by someone else, for example a test build. Uninstall the old app first (your spools are on the server, not the phone), then install again.
- **The download from your server fails** ("no app package is installed on this server"): the server's copy
  is only there when it was installed from a release. Use the GitHub download instead.
- **No servers found, or "Connecting..." never finishes**:
  - Check that the phone is on the home Wi-Fi, not mobile data or a guest network.
  - On Android 17 or newer, check that **local network access** is allowed (app settings → permissions).
  - Check that the server is running: `sudo filament-kit status` on the server.
  - If the server's firewall is on, see [Install the server, Common problems](install-server.md#common-problems).
  - Use **Enter address** with the server's IP address instead of its name.
- **The code has expired or was already used**: run `sudo filament-kit pair` again and use the new code.
- **The server's certificate has changed**: the app shows both fingerprints. This is expected after you
  reinstalled the server with `--purge` or moved it to another computer: tap **Pair again** and pair as above.
  If you did not expect it, don't continue.
- **To remove a phone from the server**: `sudo filament-kit unpair` lists paired phones;
  `sudo filament-kit unpair <id>` removes one.

Next: [Using the Android app](android-app.md) (set up a printer, map its slots, add spools). More on everything else: [user guide](user-guide.md).
