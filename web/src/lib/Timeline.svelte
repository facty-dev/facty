<script>
  import { ui } from "./store.svelte.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
</script>

<div class="text-xs">
  {#each ui.turns as t}
    <div class="flex items-center gap-2 border-b border-dashed py-1">
      <Badge variant="outline" class="font-mono">{t.id}</Badge>
      <Badge variant={t.mode === "deterministic" ? "secondary" : t.mode === "ranked" ? "default" : "destructive"}>{t.mode}</Badge>
      {#if t.surface}<Badge variant="outline">{t.surface}</Badge>{/if}
      {#if t.actor}<Badge variant="outline">{t.actor}</Badge>{/if}
      {#if t.choice}<Badge variant="outline">pick: {t.choice}</Badge>{/if}
      <span class="truncate">{t.step} ({t.op})</span>
    </div>
  {/each}
  {#each ui.commits as c}
    <div class="flex items-center gap-2 border-b border-dashed py-1">
      <Badge variant="outline" class="font-mono">{c.identifier?.slice(0, 10)}</Badge>
      <Badge variant="secondary">saved step</Badge>
      <span class="truncate">{c.message}</span>
    </div>
  {:else}
    <div class="text-muted-foreground">nothing recorded yet</div>
  {/each}
</div>
