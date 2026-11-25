import * as api from "./api.js";

// All UI state lives here; the server (facty serve / TerminusDB commits) is the
// only source of truth — SSE pushes replace `docs`/`commits`.
//
// Plain-language layering (UX rule for this UI): non-technical users see
// conclusions, questions and documents; ids, proofs, derivations and turn
// logs live behind the "Details" tab. Every technical concept gets a human
// name here, once.
class UI {
  case = $state("");
  cases = $state([]);
  bundles = $state([]);
  caseInfo = $state({});            // case id → {title, open, done, failed}
  docs = $state([]);
  commits = $state([]);
  surface = $state("wizard");      // "wizard" | "chat" — switchable per turn (ADR-0010)
  selected = $state(null);          // selected hypothesis id
  proofs = $state({});              // hypothesis id → [{claim, proof}]
  chat = $state([]);                // {who:"user"|"sys", text, intent?, slots?}
  error = $state("");
  notice = $state("");              // transient friendly confirmation
  feedback = $state([]);            // Feedback docs for the current case
  intent = $state(null);            // matched Goal
  dismissed = $state({});           // optional questions the person skipped (session-scoped)
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

  // ── plain-language state ──────────────────────────────────────────────────
  /** Human title for the current investigation: the pack's goal, else the case. */
  get title() { return this.goal?.name || this.case; }
  /** Ordered questions a person still has to answer (mandatory first). */
  get questions() {
    return this.gapQuestions
      .filter((q) => !this.dismissed[q.id])
      .sort((a, b) =>
        (Number(b.mandatory) - Number(a.mandatory)) || (a.priority - b.priority) || a.id.localeCompare(b.id));
  }
  dismiss(question) { this.dismissed = { ...this.dismissed, [question.id]: true }; }
  get nextQuestion() { return this.questions[0] || null; }
  /** 3-stage progress a non-technical user can act on. */
  get stage() {
    if (!this.case) return "start";
    if (this.questions.length) return "answer";
    if (!this.verdict) return "run";
    if (!this.byType("AssembledDocument")[0]) return "document";
    return "done";
  }
  /** The winning explanation, in its own prose — never an id. */
  get conclusion() {
    const w = this.verdict?.winner;
    if (!w) return null;
    const h = this.byType("Hypothesis").find((x) => x.id === w);
    if (!h) return null;
    const support = (this.byType("Constraint") || []).filter(
      (c) => c.type === "support" && c.hypothesis === w).length;
    return { id: h.id, statement: h.statement, prior: h.prior, support };
  }
  /** Explanations the evidence rules out, each with the reason in plain words. */
  get ruledOut() {
    const cons = Object.fromEntries(this.byType("Constraint").map((c) => [c.id, c]));
    return this.byType("Hypothesis")
      .filter((h) => h.status === "pruned")
      .map((h) => ({
        id: h.id,
        statement: h.statement,
        why: cons[h.prunedBy]?.reason || "it does not fit the evidence we have",
      }));
  }
  get stillExplaining() {
    return this.byType("Hypothesis").filter((h) => h.status !== "pruned");
  }
  /** One-sentence answer for the top banner. */
  get headline() {
    if (!this.case) return "Pick a situation to investigate.";
    if (this.turns.length === 0 && this.docs.length < 4) return "Loading the case…";
    if (this.questions.length) {
      const n = this.questions.length;
      return `${n} question${n === 1 ? "" : "s"} left before the investigation can run.`;
    }
    if (!this.verdict) return "Everything we need is in. Run the investigation.";
    if (this.conclusion) {
      const ruled = this.ruledOut.length;
      return `Conclusion reached — ${ruled ? `${ruled} alternative${ruled === 1 ? "" : "s"} ruled out.` : "the evidence supports one explanation."}`;
    }
    return "The investigation is complete.";
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

  async refreshBundles() {
    this.bundles = ((await api.bundles()).bundles || []).filter((b) => b.signed);
  }

  async refreshCases() {
    this.cases = ((await api.cases()).cases || []).filter((c) => c.id);
    // Titles + progress for the sidebar, in plain words. Small N (demo cases);
    // each state read is one TerminusDB query, so cap the fan-out.
    const ids = this.cases.slice(0, 12).map((c) => c.id);
    const infos = await Promise.allSettled(ids.map((id) => api.state(id)));
    const next = {};
    infos.forEach((r, i) => {
      const id = ids[i];
      if (r.status !== "fulfilled") return;
      const docs = r.value.docs || [];
      const goal = docs.find((d) => d["@type"] === "Goal");
      const hyps = docs.filter((d) => d["@type"] === "Hypothesis");
      const facts = docs.filter((d) => d["@type"] === "Fact");
      const openQ = docs.filter((d) => d["@type"] === "OpenQuestion" && d.status === "open");
      // count only the questions that are still genuine gaps (same rule the
      // wizard uses), so the sidebar and the header never disagree
      const filled = (slot) => facts.some(
        (f) => f.subject === slot.producesSubject && f.predicate === slot.producesPredicate &&
               /^(answer|sense|pipeline):/.test(f.source || ""));
      const gaps = openQ.filter((q) => {
        const slot = (goal?.requiredSlots || []).find((sl) => sl.name === q.slot);
        return !slot || !filled(slot);
      });
      const hasVerdict = docs.some((d) => d["@type"] === "Verdict");
      const hasDoc = docs.some((d) => d["@type"] === "AssembledDocument");
      next[id] = {
        title: goal?.name || id,
        open: gaps.length,
        done: hasDoc && hasVerdict,
        started: hyps.length > 0 && hasVerdict,
      };
    });
    // disambiguate repeated goal titles ("… (2)") so two cases for the same
    // kind of matter never look like one row duplicated
    const seen = {};
    for (const id of Object.keys(next)) {
      const t = next[id].title;
      seen[t] = (seen[t] || 0) + 1;
      if (seen[t] > 1) next[id].title = `${t} (${seen[t]})`;
    }
    this.caseInfo = next;
  }

  async selectCase(c) {
    this.case = c; this.chat = []; this.proofs = {}; this.selected = null; this.intent = null; this.dismissed = {};
    this.error = ""; this.notice = "";
    if (this.es) { this.es.close(); this.es = null; }
    if (!c) { this.docs = []; this.commits = []; return; }
    const [s, l, fb] = await Promise.all([api.state(c), api.log(c), api.feedbackList(c)]);
    this.docs = s.docs; this.commits = l; this.feedback = fb.feedback || [];
    this.es = new EventSource(`/api/watch?case=${encodeURIComponent(c)}`);
    this.es.addEventListener("state", (e) => { this.docs = JSON.parse(e.data).docs; });
    this.es.addEventListener("commit", (e) => { this.commits = [JSON.parse(e.data), ...this.commits]; });
  }

  /** Start a new investigation from a signed bundle (a template a human picks
   *  by its title, never by its path). Optionally seed the example evidence. */
  async startCase(bundle, { withExample = true } = {}) {
    this.error = ""; this.notice = "";
    const base = bundle.id;
    const taken = new Set(this.cases.map((c) => c.id));
    let id = base; let n = 2;
    while (taken.has(id)) { id = `${base}-${n++}`; }
    try {
      await api.caseInit(id, `bundles/${bundle.id}`);
      if (withExample) {
        try { await api.loadFacts(id, `bundles/${bundle.id}/fixtures/facts-initial.json`); }
        catch { /* bundle has no starter facts — fine */ }
      }
      // run once so the pack opens its questions (they are engine-opened docs,
      // not a static form) — deterministic and cheap, and the person then
      // starts on "answer these" instead of "run something unexplained"
      try { await api.run(id, "1"); } catch { /* an empty case is still usable */ }
      await this.refreshCases();
      await this.selectCase(id);
      this.notice = "Investigation started. Answer the questions that are left.";
    } catch (e) { this.error = String(e.message || e); }
  }

  async op(fn, ...args) {
    this.error = ""; this.notice = "";
    try { await fn(...args); await this.selectCase(this.case); }
    catch (e) { this.error = String(e.message || e); }
  }

  /** Answer one question, then re-run the deterministic engine so the rings and
   *  the conclusion update immediately (cheap: pure functions over the graph). */
  async answerQuestion(question, value) {
    this.error = ""; this.notice = "";
    try {
      await api.answer(this.case, question.id, String(value));
      await api.run(this.case, "1");
      await this.selectCase(this.case);
      await this.refreshCases();
      this.notice = "Saved. The picture below is updated.";
    } catch (e) { this.error = String(e.message || e); }
  }

  /** The one primary action a non-technical user needs. */
  async runInvestigation() {
    this.error = ""; this.notice = "";
    try {
      await api.run(this.case, "1");
      await this.selectCase(this.case);
      await this.refreshCases();
      this.notice = "Investigation run — every conclusion below is replayable.";
    } catch (e) { this.error = String(e.message || e); }
  }

  async buildDocument() {
    this.error = ""; this.notice = "";
    try {
      await api.assemble(this.case);
      await this.selectCase(this.case);
      await this.refreshCases();
      this.notice = "Document built from the parts the evidence proves.";
    } catch (e) { this.error = String(e.message || e); }
  }

  // in-UI comment channel: committed as a Feedback doc on the case branch,
  // readable via `facty feedback list --case <id>` (audit-friendly)
  async addFeedback(text, screen) {
    this.error = ""; this.notice = "";
    try {
      await api.feedbackAdd(this.case, text, screen);
      this.feedback = (await api.feedbackList(this.case)).feedback || [];
      this.notice = "comment saved — it is stored with the case (facty feedback list)";
    } catch (e) { this.error = String(e.message || e); }
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
    if (slots.length) { try { await api.run(this.case, "1"); } catch { /* keep the chat usable */ } }
    const bits = [];
    if (intent) bits.push(`this looks like “${intent.name}”`);
    if (slots.length) bits.push(`noted: ${slots.map((s) => s.slot.name).join(", ")}`);
    this.chat = [...this.chat, {
      who: "sys",
      text: bits.length ? bits.join(" · ") : "I couldn't pick anything out of that — try the questionnaire, or name a date like 2026-04-18.",
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
