<script>
  import { ui } from "./store.svelte.js";
  let drill = $state(null); // "proven" | "open" | "anomalies" | null
  const R = [46, 86, 126];
  const C = ["var(--proven)", "var(--open)", "var(--anomaly)"];
</script>

<div class="flex gap-4 flex-wrap">
  <svg width="290" height="290" viewBox="0 0 290 290" class="rounded-lg bg-muted/40">
    {#each [2, 1, 0] as ring}
      <circle cx="145" cy="145" r={R[ring]} fill="none" stroke={C[ring]} stroke-width="1.5" opacity="0.8"
              class="cursor-pointer" onclick={() => (drill = ["proven", "open", "anomalies"][ring])} />
    {/each}
    <text x="145" y="118" text-anchor="middle" fill="var(--proven)" font-size="12" font-weight="700">PROVEN</text>
    <text x="145" y="133" text-anchor="middle" fill="currentColor" font-size="16">{ui.bullseye.proven.count}</text>
    <text x="145" y="172" text-anchor="middle" fill="var(--open)" font-size="12" font-weight="700">OPEN</text>
    <text x="145" y="187" text-anchor="middle" fill="currentColor" font-size="16">{ui.bullseye.open.count}</text>
    <text x="145" y="232" text-anchor="middle" fill="var(--anomaly)" font-size="12" font-weight="700">ANOMALIES</text>
    <text x="145" y="247" text-anchor="middle" fill="currentColor" font-size="16">{ui.bullseye.anomalies.count}</text>
  </svg>
  <div class="flex-1 min-w-44">
    <div class="text-sm text-muted-foreground">
      inner = proven (derivation-backed facts + selected snippets) · middle = open (questions + undecided hypotheses) · outer = anomalies (quarantine, contradictions) — click a ring to drill in
    </div>
    {#if drill === "proven"}
      <ul class="mt-2 list-disc pl-5 text-sm">{#each ui.bullseye.proven.ids as id}<li><code class="text-xs">{id}</code></li>{/each}</ul>
    {:else if drill === "open"}
      <ul class="mt-2 list-disc pl-5 text-sm">
        {#each ui.openQuestions as q}<li>Q {q.id} — {q.text}</li>{/each}
        {#each ui.byType("Hypothesis").filter((h) => h.status !== "pruned") as h}<li>{h.id} — {h.statement.slice(0, 80)}</li>{/each}
      </ul>
    {:else if drill === "anomalies"}
      <ul class="mt-2 list-disc pl-5 text-sm">
        {#each ui.byType("Quarantine") as q}<li>quarantine {q.path}: {q.reason}</li>{/each}
        {#each ui.byType("Fact").filter((f) => f.predicate === "semanticContradictionWith") as f}
          <li>contradiction candidate <code class="text-xs">{f.subject}</code> ~ <code class="text-xs">{f.valueString}</code> ({Number(f.confidence).toFixed(3)})</li>
        {/each}
      </ul>
    {/if}
  </div>
</div>
