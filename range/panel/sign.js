/* Post-mortem signing in the browser (WebCrypto Ed25519).
 *
 * The private key is generated here, marked non-extractable and kept in
 * IndexedDB: it never leaves the browser, not even for the panel's own code.
 * The grader verifies the signature with the matching public key (PEM) over
 *   "vantage-debrief-v1\n<attempt id>\n<sha256 hex of the markdown>\n"
 * exactly like framework/debrief.py message() does for the CLI.
 *
 * Works as a plain <script> (window.VantageSign) and as a CommonJS module
 * (range/tests/test_webcrypto.py runs it in Node against the real grader).
 */
(function (root) {
  "use strict";
  const enc = new TextEncoder();
  const subtle = () => (root.crypto || globalThis.crypto).subtle;

  const hex = (buf) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
  const b64 = (buf) => {
    let s = "";
    new Uint8Array(buf).forEach((b) => { s += String.fromCharCode(b); });
    return btoa(s);
  };

  async function messageFor(attemptId, markdown) {
    const digest = await subtle().digest("SHA-256", enc.encode(markdown));
    return enc.encode("vantage-debrief-v1\n" + attemptId + "\n" + hex(digest) + "\n");
  }

  function pem(spki) {
    const lines = b64(spki).match(/.{1,64}/g).join("\n");
    return "-----BEGIN PUBLIC KEY-----\n" + lines + "\n-----END PUBLIC KEY-----\n";
  }

  async function supported() {
    try {
      await subtle().generateKey({ name: "Ed25519" }, false, ["sign", "verify"]);
      return true;
    } catch (e) {
      return false;
    }
  }

  async function generate() {
    // extractable=false applies to the private key; the public key can always be exported
    return subtle().generateKey({ name: "Ed25519" }, false, ["sign", "verify"]);
  }

  async function publicInfo(pair) {
    const spki = await subtle().exportKey("spki", pair.publicKey);
    return { pem: pem(spki), fingerprint: hex(await subtle().digest("SHA-256", spki)) };
  }

  async function sign(pair, attemptId, markdown) {
    const sig = await subtle().sign({ name: "Ed25519" }, pair.privateKey, await messageFor(attemptId, markdown));
    return { pubkey: (await publicInfo(pair)).pem, signature: b64(sig) };
  }

  // --- key storage: one key pair per user, in this browser only -----------------
  function db() {
    return new Promise((resolve, reject) => {
      const r = indexedDB.open("vantage-keys", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("keys");
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  }
  async function store(mode, fn) {
    const d = await db();
    return new Promise((resolve, reject) => {
      const t = d.transaction("keys", mode);
      const req = fn(t.objectStore("keys"));
      t.oncomplete = () => resolve(req && req.result);
      t.onerror = () => reject(t.error);
    });
  }
  const loadKey = (user) => store("readonly", (s) => s.get(user));
  const saveKey = (user, pair) => store("readwrite", (s) => s.put(pair, user));

  const api = { messageFor, pem, supported, generate, publicInfo, sign, loadKey, saveKey };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VantageSign = api;
})(typeof self !== "undefined" ? self : globalThis);
