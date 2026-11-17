<script>
  import { ui } from "./store.svelte.js";
  import * as api from "./api.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";

  let values = $state({});

  async function submit(q) {
    const v = values[q.id];
    if (v === undefined || v === "") return;
    await ui.op(api.answer, ui.case, q.id, String(v));
    values[q.id] = "";
  }
</script>

{#if ui.goal}
  <div class="mb-2 text-sm text-muted-foreground">goal: <b class="text-foreground">{ui.goal.name}</b> — {ui.goal.statement}</div>
{/if}
{#if ui.gapQuestions.length === 0}
  <div class="text-sm text-muted-foreground">no open questions — every required slot is filled. Run the engine to chain → prune → rank.</div>
{/if}
{#each ui.gapQuestions as q (q.id)}
  {@const slot = ui.goal?.requiredSlots?.find((s) => s.name === q.slot)}
  <div class="my-2 rounded-lg border bg-muted/30 p-3">
    <div class="text-sm">{q.text}</div>
    <div class="mt-2 flex items-center gap-2 flex-wrap">
      <Label class="text-xs text-primary">slot: {q.slot}{slot ? ` (${slot.type})` : ""}</Label>
      {#if slot?.type === "bool"}
        <Select.Root type="single" bind:value={values[q.id]}>
          <Select.Trigger class="w-24"><Select.Value placeholder="—" /></Select.Trigger>
          <Select.Content>
            <Select.Item value="true">yes</Select.Item>
            <Select.Item value="false">no</Select.Item>
          </Select.Content>
        </Select.Root>
      {:else if slot?.type === "num"}
        <Input type="number" class="w-32" bind:value={values[q.id]} />
      {:else if slot?.type === "date"}
        <Input type="date" class="w-40" bind:value={values[q.id]} />
      {:else}
        <Input class="w-56" bind:value={values[q.id]} onkeydown={(e) => e.key === "Enter" && submit(q)} />
      {/if}
      <Button size="sm" onclick={() => submit(q)}>answer</Button>
      <span class="text-xs text-muted-foreground">prio {q.priority} · discriminates {(q.discriminates || []).join(", ") || "—"}</span>
    </div>
  </div>
{/each}
