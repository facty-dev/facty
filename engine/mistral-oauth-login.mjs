// mistral-oauth-login.mjs — run the pi-mistral-subscription extension's
// OWN OAuth login (behind the scenes) and print the flow's milestones
// for the workbench to relay:
//
//   URL:<sign-in url>     open it in a browser to complete the sign-in
//   PROGRESS:<message>    flow progress
//   CRED:<credentials>    the finished credential (JSON) — the caller
//                         stores it in pi's auth storage
//   ERROR:<message>       the flow failed
//
// Usage: node mistral-oauth-login.mjs <path-to-mistral-oauth.ts>
//
// The extension's code does the real work (PKCE, the sign-in process,
// polling, the token exchange) — this driver only wires its callbacks to
// stdout. Node >= 22.19 strips the extension's TypeScript types.

import { pathToFileURL } from "node:url";

const oauthPath = process.argv[2];
if (!oauthPath) {
  console.error("usage: node mistral-oauth-login.mjs <path-to-mistral-oauth.ts>");
  process.exit(2);
}
const { createMistralOAuth } = await import(pathToFileURL(oauthPath).href);
const oauth = createMistralOAuth();

try {
  const creds = await oauth.login({
    onAuth: ({ url, instructions }) => {
      console.log("URL:" + url);
      if (instructions) console.log("PROGRESS:" + instructions);
    },
    onProgress: (msg) => console.log("PROGRESS:" + msg),
  });
  console.log("CRED:" + JSON.stringify(creds));
} catch (err) {
  console.log("ERROR:" + (err && err.message ? err.message : String(err)));
  process.exit(1);
}
