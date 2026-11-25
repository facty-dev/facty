<script>
  import { ui } from "./store.svelte.js";
  import { Badge } from "$lib/components/ui/badge/index.js";

  function renderTree(t, depth = 0) {
    if (!t) return "not provable from the evidence";
    const g = `${t.goal?.subject ?? "?"} ${t.goal?.predicate ?? "?"}`;
    if (t.by === "fact") return `${"  ".repeat(depth)}${g}  ← fact ${t.fact} (${t.source || "?"})`;
    const premises = (t.premises || []).map((p) => renderTree(p, depth + 1)).join("\n");
    return `${"  ".repeat(depth)}${g}  ← rule ${t.rule} (derived ${t.fact ?? ""})\n${premises}`;
  }
</script>

{#if ui.selected && ui.proofs[ui.selected]}
  {#each ui.proofs[ui.selected] as p}
    <div class="my-1.5">
      <Badge variant={p.provable ? "default" : "destructive"} class="mr-1.5">{p.provable ? "proven" : "not provable yet"}</Badge>
      <code class="text-xs">{p.claim.subject} {p.claim.predicate} = {p.claim.valueBool ?? p.claim.valueNum ?? p.claim.valueString ?? "*"}</code>
      {#if p.proof}<pre class="mt-1 overflow-x-auto rounded-md bg-muted p-2 text-xs">{renderTree(p.proof)}</pre>{/if}
    </div>
  {/each}
{:else if ui.selected}
  <div class="text-sm text-muted-foreground">proving…</div>
{:else}
  <div class="text-sm text-muted-foreground">pick an explanation on the left to see the chain of rules and documents behind it</div>
{/if}
