// Thin client of the `facty serve` gateway — the ONLY backend the UI talks to
// (ADR-0010 parity: same ops the CLI exposes).
export async function api(path, body) {
  const opt = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `${path}: HTTP ${r.status}`);
  return j;
}

export const cases = () => api("/api/cases");
export const state = (c) => api(`/api/state?case=${encodeURIComponent(c)}`);
export const log = (c) => api(`/api/log?case=${encodeURIComponent(c)}`);
export const run = (c, phase = "1") => api("/api/run", { case: c, phase });
export const prove = (c, subject, predicate, value) =>
  api("/api/prove", { case: c, subject, predicate, value });
export const assemble = (c) => api("/api/assemble", { case: c });
export const answer = (c, question, value) => api("/api/answer", { case: c, question, value });
export const ingest = (c, dir, source = "ui") => api("/api/ingest", { case: c, dir, source });
export const loadFacts = (c, path) => api("/api/load-facts", { case: c, path });
export const caseInit = (id, bundle) => api("/api/case/init", { id, bundle });
export const turn = (c, opts = {}) => api("/api/turn", { case: c, ...opts });
export const feedbackAdd = (c, text, screen) =>
  api("/api/feedback", { case: c, text, screen, author: "ui-user", at: new Date().toISOString() });
export const feedbackList = (c) => api(`/api/feedback?case=${encodeURIComponent(c ?? "")}`);
