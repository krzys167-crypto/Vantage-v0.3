// Node harness for range/panel/sign.js: signs a post-mortem the way the browser does.
//   node webcrypto_sign.js <attempt id> <markdown file>   -> {"pubkey", "signature", "fingerprint"}
const fs = require("fs");
const path = require("path");
const sign = require(path.join(__dirname, "..", "panel", "sign.js"));

(async () => {
  const [aid, file] = process.argv.slice(2);
  const md = fs.readFileSync(file, "utf8");
  if (!(await sign.supported())) { console.log(JSON.stringify({ unsupported: true })); return; }
  const pair = await sign.generate();
  const info = await sign.publicInfo(pair);
  const out = await sign.sign(pair, aid, md);
  let extractable = true;
  try { await crypto.subtle.exportKey("pkcs8", pair.privateKey); } catch (e) { extractable = false; }
  console.log(JSON.stringify({ pubkey: out.pubkey, signature: out.signature, fingerprint: info.fingerprint,
                               private_key_extractable: extractable }));
})().catch((e) => { console.error(e); process.exit(1); });
