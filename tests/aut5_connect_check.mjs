// Test driver for tests/test_aut5_connect.py: connectToPage (tests/aut5_run.mjs) against a fake DevTools endpoint that
// refuses, errors and shows no page before it answers. Prints "ok <phase>" lines; exits 1 on a failed expectation.
import { createServer } from "node:http";
import { connectToPage } from "./aut5_run.mjs";

const fake = (script) => new Promise((res) => {
  let n = 0;
  const srv = createServer((req, rsp) => {
    const step = script[Math.min(n++, script.length - 1)];
    if (step === "drop") req.socket.destroy();
    else if (step === "503") { rsp.statusCode = 503; rsp.end("not yet"); }
    else if (step === "empty") rsp.end("[]");
    else rsp.end(JSON.stringify([{ type: "page", webSocketDebuggerUrl: "ws://127.0.0.1:1/x" }]));
  }).listen(0, "127.0.0.1", () => res({ srv, port: srv.address().port, calls: () => n }));
});
let failed = false;
const expect = (name, ok, detail = "") => { console.log(`${ok ? "ok" : "FAIL"} ${name} ${detail}`); failed ||= !ok; };

{   // the first requests fail in turn, then the page appears
  const { srv, port, calls } = await fake(["drop", "drop", "503", "empty", "empty", "page"]);
  let tries = 0;
  const r = await connectToPage(port, { limitMs: 5000, open: async () => { if (++tries < 2) throw new Error("early"); return "socket"; } });
  expect("waits for the endpoint and the page", r.ws === "socket" && calls() === 6, `calls=${calls()}`);
  expect("retries the socket once", tries === 2, `tries=${tries}`);
  srv.close();
}
{   // never answers: the error names the phase
  const { srv, port } = await fake(["503"]);
  const e = await connectToPage(port, { limitMs: 600 }).catch((x) => x);
  expect("names the target list phase", e instanceof Error && /target list not ready after/.test(e.message), e.message);
  srv.close();
}
{   // answers but never has a page
  const { srv, port } = await fake(["empty"]);
  const e = await connectToPage(port, { limitMs: 600 }).catch((x) => x);
  expect("names the page target phase", e instanceof Error && /page target not ready after/.test(e.message), e.message);
  srv.close();
}
{   // the socket never opens
  const { srv, port } = await fake(["page"]);
  const e = await connectToPage(port, { limitMs: 600, open: async () => { throw new Error("refused"); } }).catch((x) => x);
  expect("names the socket phase", e instanceof Error && /socket did not open twice/.test(e.message), e.message);
  srv.close();
}
process.exit(failed ? 1 : 0);
