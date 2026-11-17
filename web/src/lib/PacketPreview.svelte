<script>
  import { marked } from "marked";
  import { ui } from "./store.svelte.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Printer } from "@lucide/svelte";
  const doc = $derived(ui.byType("AssembledDocument")[0]);
  const html = $derived(doc ? marked.parse(doc.content) : "");
</script>

{#if doc}
  <div class="mb-2 flex items-center gap-2 flex-wrap">
    <span class="text-xs text-muted-foreground">{doc.id} · goal {doc.goal} · verdict {doc.verdict ?? "—"} · {doc.snippets.length} snippets · sha256 {doc.sha256.slice(0, 12)}</span>
    <div class="flex-1"></div>
    <Button variant="outline" size="sm" onclick={() => window.print()}><Printer class="size-4" /> print / PDF</Button>
  </div>
  <div class="rounded-lg border bg-white p-6 text-black [&_h1]:mb-3 [&_h1]:text-2xl [&_h1]:font-bold [&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:text-lg [&_h2]:font-semibold [&_p]:my-2 [&_strong]:font-bold">
    {@html html}
  </div>
{:else}
  <div class="text-sm text-muted-foreground">nothing assembled yet — press <b>assemble</b> (deterministic: snippets whose <code>when</code> is proven are rendered, then committed as an AssembledDocument)</div>
{/if}
