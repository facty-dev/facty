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
    <text x="145" y="127" text-anchor="middle" fill="var(--proven)" font-size="10" font-weight="700">PROVEN</text>
    <text x="145" y="146" text-anchor="middle" fill="currentColor" font-size="15">{ui.bullseye.proven.count}</text>
    <text x="145" y="203" text-anchor="middle" fill="var(--open)" font-size="10" font-weight="700">OPEN</text>
    <text x="145" y="219" text-anchor="middle" fill="currentColor" font-size="15">{ui.bullseye.open.count}</text>
    <text x="145" y="243" text-anchor="middle" fill="var(--anomaly)" font-size="9" font-weight="700">DOESN'T FIT</text>
    <text x="145" y="259" text-anchor="middle" fill="currentColor" font-size="15">{ui.bullseye.anomalies.count}</text>
  </svg>
  <div class="flex-1 min-w-44">
    <div class="text-sm text-muted-foreground">
      <p><span class="font-medium" style="color: var(--proven)">Inner</span> — what the evidence proves.</p>
      <p><span class="font-medium" style="color: var(--open)">Middle</span> — questions to answer and explanations still in play.</p>
      <p><span class="font-medium" style="color: var(--anomaly)">Outer</span> — things that don't fit together and need a look.</p>
      <p class="mt-1 text-xs">Click a ring to see the items.</p>
    </div>
    {#if drill === "proven"}
      <ul class="mt-2 list-disc pl-5 text-sm">
        {#each ui.bullseye.proven.ids as id}<li><code class="text-xs">{id}</code></li>{:else}<li>nothing proven yet</li>{/each}
      </ul>
    {:else if drill === "open"}
      <ul class="mt-2 list-disc pl-5 text-sm">
        {#each ui.questions as q}<li>{q.text}</li>{/each}
        {#each ui.stillExplaining as h}<li>{h.statement.slice(0, 90)}…</li>{/each}
        {#if !ui.questions.length && !ui.stillExplaining.length}<li>nothing open</li>{/if}
      </ul>
    {:else if drill === "anomalies"}
      <ul class="mt-2 list-disc pl-5 text-sm">
        {#each ui.byType("Quarantine") as q}<li>{q.path}: {q.reason}</li>{/each}
        {#each ui.byType("Fact").filter((f) => f.predicate === "semanticContradictionWith") as f}
          <li>two documents disagree about <b>{f.subject}</b> ({Number(f.confidence).toFixed(2)} confidence)</li>
        {/each}
        {#if !ui.bullseye.anomalies.count}<li>nothing out of place</li>{/if}
      </ul>
    {/if}
  </div>
</div>
