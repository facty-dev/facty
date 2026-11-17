<script>
  import { ui } from "./store.svelte.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { ScrollArea } from "$lib/components/ui/scroll-area/index.js";

  let text = $state("");
  async function send() {
    if (!text.trim()) return;
    const t = text; text = "";
    await ui.sendChat(t);
  }
</script>

<ScrollArea class="h-64">
  <div class="flex flex-col gap-2 pr-3">
    {#each ui.chat as m}
      <div class="max-w-[85%] rounded-lg px-3 py-1.5 text-sm {m.who === "user" ? "self-end bg-primary text-primary-foreground" : "self-start bg-muted"}">
        {m.text}
        {#if m.intent}<Badge variant="outline" class="ml-1">deterministic</Badge>{/if}
        {#if m.slots}<Badge variant="outline" class="ml-1">ranked</Badge>{/if}
      </div>
    {/each}
  </div>
</ScrollArea>
<div class="mt-2 flex gap-2">
  <Input class="flex-1" placeholder="e.g. “the goods were delivered on 2026-04-18 and never rejected in writing”"
         bind:value={text} onkeydown={(e) => e.key === "Enter" && send()} />
  <Button onclick={send}>send</Button>
</div>
<div class="mt-1 text-xs text-muted-foreground">every utterance goes through intent recognition + slot filling — chat answers fill the same slots as wizard answers (same Fact, same <code>answer:</code> tag)</div>
