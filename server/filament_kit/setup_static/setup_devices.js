// The Devices section's cards: readers, pairing, stations asking to pair and the phone web app.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

// ----- readers -----
function readersCard() {
  const R = S.readers, box = boxFor("readers"), name = h("input", { placeholder: "reader name, e.g. printer-station" });
  return card("NFC readers",
    R.error ? h("p", { class: "err", textContent: R.error }) : null,
    ...R.list.map((t) => { const at = boxFor("reader:" + t.id); return h("div", { class: "row item", "data-key": t.id }, h("span", { textContent: `${t.id} · ${t.name} · made ${t.created}` }),
      h("button", { class: "secondary", textContent: "Revoke", on: { click: () => asking(at, `readers/${encodeURIComponent(t.id)}/revoke`,
        destroy("devices_revoke_token_title", "devices_revoke_token_body", "devices_revoke_token_confirm", { id: t.id }), undefined,
        () => say(at, SW.t("devices_token_revoked", { id: t.id }), true)) } }), at); }),
    R.list.length ? null : h("p", { class: "muted", textContent: "No reader tokens." }),
    h("div", { class: "row" }, name, h("button", { textContent: "Make a token", on: { click: () => change(box, "readers", { name: name.value },
      (r) => say(box, [h("p", { textContent: `New reader token ${r.id} (${r.name}):` }), h("pre", { class: "ok", textContent: r.token }), h("p", { class: "muted", textContent: r.note })], true)) } })),
    box);
}

// ----- pairing -----
let qrUrl = null;
let pairWatch = 0;      // the newest pairing shown; an older watch stops
// Says when a pairing shown in `box` is claimed: a device that `known` does not hold has appeared. Stops at `seconds`.
function watchPaired(box, known, seconds) {
  const me = ++pairWatch;
  const until = Date.now() + seconds * 1000;
  const tick = async () => {
    if (me !== pairWatch || Date.now() > until) return;
    let s = null;
    try { s = await api("state"); } catch { /* the server may be restarting: the next try tells */ }
    if (me !== pairWatch) return;
    const fresh = s && s.devices.find((d) => !known.has(d.id));
    if (fresh) { await refresh(box); say(box, `Paired: ${fresh.name}.`, true); return; }
    setTimeout(tick, 3000);
  };
  setTimeout(tick, 3000);
}
function pairCard() {
  const box = boxFor("pair");
  async function start(kind) {
    const known = new Set(S.devices.map((d) => d.id));
    const r = await change(box, "pair", { kind }, () => {});
    if (!r) return;
    watchPaired(box, known, r.expires_in);
    if (qrUrl) URL.revokeObjectURL(qrUrl);
    qrUrl = r.qr_svg ? URL.createObjectURL(new Blob([r.qr_svg], { type: "image/svg+xml" })) : null;
    say(box, [
      kind === "phone" ? h("p", { textContent: "Open the filament-kit app and scan this code, or type the pairing code." }) :
        h("p", { textContent: kind === "pc" ? "Paste this link into filament-kit-sync when it asks:" : "On the station PC run: sudo filament-kit station pair, then paste this link:" }),
      qrUrl ? h("img", { class: "qr", alt: "Pairing QR code", src: qrUrl }) : null,
      kind === "phone" ? null : h("pre", { class: "ok", textContent: r.link }),
      h("p", {}, "Pairing code: ", h("b", { textContent: r.code })),
      h("p", { class: "muted", textContent: `Certificate fingerprint (${kind === "phone" ? "the phone asks for two groups of it" : "check it matches"}): ${r.fingerprint}` }),
      h("p", { class: "muted", textContent: `Expires in ${Math.round(r.expires_in / 60)} min.` })], "info");
  }
  return card("Phones, PC and station",
    ...S.devices.map((d) => { const at = boxFor("device:" + d.id); return h("div", { class: "row item", "data-key": d.id }, h("span", { textContent: `${d.name} · paired ${d.paired || "?"} · last seen ${d.last_seen || "never"}` }),
      d.built_in ? h("span", { class: "muted", textContent: "built in: this server's own pairing" })
        : h("button", { class: "secondary", textContent: "Revoke", on: { click: () => asking(at, `devices/${encodeURIComponent(d.id)}/revoke`,
          destroy("devices_unpair_title", "devices_unpair_body", "devices_unpair", { name: d.name }), undefined,
          () => say(at, SW.t("devices_unpaired", { name: d.name }), true)) } }), at); }),
    S.devices.length ? null : h("p", { class: "muted", textContent: "Nothing paired yet." }),
    h("div", { class: "row" },
      h("button", { textContent: "Pair a phone", on: { click: () => start("phone") } }),
      h("button", { class: "secondary", textContent: "Link for the PC sync", on: { click: () => start("pc") } }),
      h("button", { class: "secondary", textContent: "Link for the station", on: { click: () => start("station") } }),
      S.modules.some((m) => m.name === "station" && m.on) ? h("button", { class: "secondary", textContent: "Pair the station on this machine", on: { click: () => startJob(box, "station_pair") } }) : null),
    box);
}

// Stations on other computers that ask to pair: Pair only when the station's screen shows the same six digits.
function stationAsksCard() {
  const body = h("div");
  const show = async () => {
    try {
      const r = await api("stations/requests", { code: theCode() });
      fill(body,
        r.requests.length ? null : h("p", { class: "muted", textContent: "No station is asking to pair." }),
        ...r.requests.map((q) => { const box = boxFor("request:" + q.id); return h("div", { class: "item", "data-key": q.id },
          h("p", {}, `${q.name} at ${q.address} asks to pair. Its screen shows `, h("b", { textContent: `${q.code.slice(0, 3)} ${q.code.slice(3)}` }), "."),
          h("p", { class: "muted", textContent: "Pair only if the station shows the same six digits. If not, refuse: someone else asked." }),
          h("div", { class: "row" },
            h("button", { textContent: "Pair", on: { click: () => change(box, `stations/requests/${q.id}/pair`, {}, () => say(box, `Paired ${q.name}. It picks up its pairing within a few seconds.`, true)) } }),
            h("button", { class: "secondary", textContent: "Refuse", on: { click: () => change(box, `stations/requests/${q.id}/refuse`, {}, () => fill(box)) } })), box); }));
    } catch (e) { if (e.locked) throw e; say(body, e.message, false); }
  };
  return card("Stations asking to pair", h("p", { class: "muted", textContent: "An intake station on another computer asks from its own screen." }),
    codeRead("devices_requests_locked", body, show));
}

let webQrUrls = [];
// The iPhone is not paired: it opens the phone web app in Safari, served by this server at home (and by the web
// module at its public address, when that is on).
function webAppCard() {
  const body = h("div");
  const note = h("div", { role: "status" });     // the hidden-values note; the card (home address, QR) stays
  const el = card("iPhone: the web app", body, note);
  const load = (whole) => (whole ? api("webapp", { code: theCode() }) : api("webapp")).then((r) => {
    note.replaceChildren(...(r.public_hidden ? [lockNote("lock_hidden_note")] : []));
    webQrUrls.forEach((u) => URL.revokeObjectURL(u));
    webQrUrls = [];
    const qr = (svg, alt) => {
      if (!svg) return null;
      const u = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
      webQrUrls.push(u);
      return h("img", { class: "qr", alt, src: u });
    };
    fill(body,
      h("p", {}, "At home, open this address in Safari: ", h("b", { textContent: r.url })),
      qr(r.qr_svg, "QR code of the web app's home address"),
      h("p", { class: "muted", textContent: "Safari warns once about the server's own certificate: accept it to go on. It works on the home network only." }),
      r.public_url ? h("p", {}, "Away from home too (the web module): ", h("b", { textContent: r.public_url })) : null,
      r.public_url ? qr(r.public_qr_svg, "QR code of the web app's public address") : null,
      h("p", { textContent: "To keep it on the iPhone: tap Share, then Add to Home Screen." }));
  });
  whenOpen(body, load);
  return el;
}
