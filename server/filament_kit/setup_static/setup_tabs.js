// What the console's own sections share: the wiring of the background job strip, dates, links and starting a job.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

const fmtDate = (t) => (t ? new Date(t * 1000).toLocaleString() : null);
const link = (tab, text) => h("a", { href: "#" + tab, textContent: text });

// ----- a background job (apply, update, rollback, check): it outlives the server, so the page waits for it -----
// The strip, the top-bar indicator, the restarting state and the not-answering banner are SW_JOBS' (02 8.4, 8.5; 03 3.5 to
// 3.7); this is the page's part: its requests, the whole log behind the lock, and what is read again when a job ends.
let hubJobsMade = null;
const hubJobs = () => hubJobsMade || (hubJobsMade = SW_JOBS.create({
  job: (from) => api(`job?from=${from}`),
  state: () => api("state"),
  version: () => (S ? S.version : null),
  banners: () => document.querySelector("main"),
  onEnd: () => refresh(),
  onBack: () => refresh(),
  // read only when pressed, it can be long (03 2.1); while Locked it asks for the code in place
  wholeLog: async (box) => {
    let text = null;
    await coded(box, async () => {
      let at = 0, all = "";
      for (;;) {
        const r = await api("job/log", { from: at, code: theCode() });
        all += r.text;
        if (r.next === at) break;
        at = r.next;
      }
      text = all;
    });
    return text;
  },
}));
const followApply = (fresh) => hubJobs().follow(fresh);

// ----- Updates -----
// `question`: the ask options of its dialog (10.11, 12.3); the job starts once it is confirmed
function startJob(box, name, question) {
  const started = () => { fill(box); followApply(true); };
  if (question) asking(box, "job", question, () => ({ name }), started); else change(box, "job", { name }, started);
}
