import * as api from "./api.js";

// All UI state lives here; the server (facty serve / TerminusDB commits) is the
// only source of truth — SSE pushes replace `docs`/`commits`.
class UI {
  case = $state("");
  cases = $state([]);
  docs = $state([]);
  commits = $state([]);
  surface = $state("wizard");      // "wizard" | "chat" — switchable per turn (ADR-0010)
  selected = $state(null);          // selected hypothesis id
  proofs = $state({});              // hypothesis id → [{claim, proof}]
  chat = $state([]);                // {who:"user"|"sys", text, intent?, slots?}
  error = $state("");
  intent = $state(null);            // matched Goal
  es = null;

  byType(t) { return this.docs.filter((d) => d["@type"] === t); }
  get goal() { return this.byType("Goal")[0] || null; }
  get verdict() {
    const vs = this.byType("Verdict");
    return vs.length ? vs[vs.length - 1] : null;
  }
  get ranking() { return (this.verdict?.ranking || []).slice().sort((a, b) => b.score - a.score); }
  get openQuestions() { return this.byType("OpenQuestion").filter((q) => q.status === "open"); }
  get turns() { return this.byType("Turn"); }              // per-turn audit: mode/surface/actor
  get pipeline() { return this.byType("Pipeline")[0] || null; }

  slotFilled(slot) {
    return this.byType("Fact").some(
      (f) => f.subject === slot.producesSubject && f.predicate === slot.producesPredicate &&
             /^(answer|sense|pipeline):/.test(f.source || ""));
  }
  // the questionnaire opens only for gaps (Docassemble model): unfilled slots
  get gapQuestions() {
    const goal = this.goal;
    if (!goal) return this.openQuestions;
    return this.openQuestions.filter((q) => {
      const slot = goal.requiredSlots.find((s) => s.name === q.slot);
      return !slot || !this.slotFilled(slot);
    });
  }

  // bullseye rings (USE-CASE-DOC-ASSEMBLY.md): Proven / Open / Anomalies
  get bullseye() {
    const ders = this.byType("Derivation");
    const provenIds = new Set();
    for (const d of ders) { provenIds.add(d.fact); for (const v of d.via || []) provenIds.add(v); }
    const doc = this.byType("AssembledDocument")[0];
    if (doc) for (const s of doc.snippets || []) provenIds.add("snippet:" + s);
    const openQ = this.openQuestions.length;
    const openH = this.byType("Hypothesis").filter((h) => h.status !== "pruned").length;
    const anomalies =
      this.byType("Quarantine").length +
      this.byType("Fact").filter((f) => ["semanticContradictionWith", "versionConflict"].includes(f.predicate)).length;
    return {
      proven: { count: provenIds.size, ids: [...provenIds].sort() },
      open: { count: openQ + openH, questions: openQ, openHypotheses: openH },
      anomalies: { count: anomalies },
    };
  }

  async refreshCases() {
    this.cases = ((await api.cases()).cases || []).filter((c) => c.id);
  }

  async selectCase(c) {
    this.case = c; this.chat = []; this.proofs = {}; this.selected = null; this.intent = null;
    if (this.es) { this.es.close(); this.es = null; }
    if (!c) return;
    const [s, l] = await Promise.all([api.state(c), api.log(c)]);
    this.docs = s.docs; this.commits = l;
    this.es = new EventSource(`/api/watch?case=${encodeURIComponent(c)}`);
    this.es.addEventListener("state", (e) => { this.docs = JSON.parse(e.data).docs; });
    this.es.addEventListener("commit", (e) => { this.commits = [JSON.parse(e.data), ...this.commits]; });
  }

  async op(fn, ...args) {
    this.error = "";
    try { await fn(...args); await this.selectCase(this.case); }
    catch (e) { this.error = String(e.message || e); }
  }

  // deterministic-first intent recognition (rules before LLM, ADR-0010):
  // substring match against the pack Goal's intentPhrases
  recognizeIntent(text) {
    const t = text.toLowerCase();
    const g = this.goal;
    if (!g) return null;
    const hit = (g.intentPhrases || []).find((p) => t.includes(p.toLowerCase()));
    return hit ? g : null;
  }

  // naive typed slot capture from a chat utterance (prototype of the human loop;
  // the LLM typed-candidate path lands with the Slice-2 turn dispatcher)
  captureSlots(text) {
    const g = this.goal; const out = [];
    if (!g) return out;
    const t = text.toLowerCase();
    const date = t.match(/\b(\d{4}-\d{2}-\d{2})\b/);
    const num = t.match(/\b(?:cad|\$)?\s?([\d][\d,]*(?:\.\d+)?)\b/);
    for (const s of g.requiredSlots || []) {
      if (s.type === "date" && date && /deliver|date/.test(t)) out.push({ slot: s, value: date[1] });
      else if (s.type === "num" && num && /(amount|limit|\$|owed|invoice)/.test(t)) out.push({ slot: s, value: num[1].replace(/,/g, "") });
      else if (s.type === "bool" && /(yes|no|not|never|true|false)/.test(t)) {
        const yes = /(yes|true|business|company)/.test(t) && !/(not|no|never)/.test(t);
        if (/written|rejection|complaint/.test(t)) out.push({ slot: s, value: String(yes) });
        if (/employee|worker/.test(t)) out.push({ slot: s, value: String(!yes) === "false" ? "false" : String(yes) });
      }
    }
    return out;
  }

  async sendChat(text) {
    this.chat = [...this.chat, { who: "user", text }];
    const intent = this.recognizeIntent(text);
    this.intent = intent;
    const slots = this.captureSlots(text);
    for (const { slot, value } of slots) {
      const q = this.openQuestions.find((qq) => qq.slot === slot.name);
      if (q) await api.answer(this.case, q.id, value);
    }
    const bits = [];
    if (intent) bits.push(`intent → ${intent.name}`);
    if (slots.length) bits.push(`slots → ${slots.map((s) => `${s.slot.name}=${s.value}`).join(", ")}`);
    this.chat = [...this.chat, {
      who: "sys", text: bits.length ? bits.join(" · ") : "no intent/slot recognized (LLM candidates land with the Slice-2 dispatcher)",
      intent: intent?.id, slots: slots.map((s) => s.slot.name),
    }];
    await this.selectCase(this.case);
  }

  async selectHypothesis(id) {
    this.selected = id;
    const h = this.byType("Hypothesis").find((x) => x.id === id);
    if (!h) return;
    const proofs = [];
    for (const c of h.claims || []) {
      const goal = { subject: c.subject, predicate: c.predicate };
      if ("valueBool" in c) goal.value = String(c.valueBool);
      else if ("valueNum" in c) goal.value = String(c.valueNum);
      else if ("valueString" in c) goal.value = c.valueString;
      const r = await api.prove(this.case, c.subject, c.predicate, goal.value);
      proofs.push({ claim: c, provable: r.provable, proof: r.proof });
    }
    this.proofs = { ...this.proofs, [id]: proofs };
  }
}

export const ui = new UI();
