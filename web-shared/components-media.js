// Spoolwarden shared components, the media addition (02-components.md 1.5, 7.8): loaded after components.js, only by the
// pages that show photos or a pairing code. It adds window.SW_MEDIA.
(() => {
"use strict";
// the QR block's image (7.8): the Hub's SVG through a Blob URL
const qrImage = (svgText, alt) => window.SW.h("img", { class: "qr__image", alt, width: 224, height: 224,
  src: URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" })) });

window.SW_MEDIA = Object.freeze({ qrImage });
})();
