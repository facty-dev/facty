<script>
  import { marked } from "marked";
  import { ui } from "./store.svelte.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Printer } from "@lucide/svelte";
  const doc = $derived(ui.byType("AssembledDocument")[0]);
  const html = $derived(doc ? marked.parse(doc.content) : "");
</script>

{#if doc}
  <div class="mb-3 flex items-center gap-2 flex-wrap">
    <div class="text-sm">
      <b>{ui.title}</b>
      <span class="text-muted-foreground"> — built from {doc.snippets.length} parts, each backed by evidence.</span>
    </div>
    <div class="flex-1"></div>
    <Button size="sm" onclick={() => window.print()}><Printer class="size-4" /> Print / save PDF</Button>
  </div>
  <div class="rounded-lg border bg-white p-6 text-black [&_h1]:mb-3 [&_h1]:text-2xl [&_h1]:font-bold [&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:text-lg [&_h2]:font-semibold [&_p]:my-2 [&_strong]:font-bold">
    {@html html}
  </div>
  <div class="mt-2 text-[11px] text-muted-foreground">
    Saved with the case as a committed record (sha256 {doc.sha256.slice(0, 12)}…) — the Details tab shows the proof behind each part.
  </div>
{:else if ui.questions.length}
  <div class="text-sm text-muted-foreground">
    The document is built from what the evidence proves, so it comes after the questions.
    {ui.questions.length} question{ui.questions.length === 1 ? "" : "s"} still to answer.
  </div>
{:else}
  <div class="space-y-3">
    <p class="text-sm text-muted-foreground">
      Nothing built yet. The document takes the parts the evidence proves — nothing else — and is saved with the case.
    </p>
    <Button size="sm" onclick={() => ui.buildDocument()}><Printer class="size-4" /> Build the document</Button>
  </div>
{/if}
