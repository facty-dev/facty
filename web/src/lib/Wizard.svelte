<script>
  import { ui } from "./store.svelte.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";

  // One question at a time (a person in a hurry should never scan a form).
  let values = $state({});

  const total = $derived(ui.byType("Goal")[0]?.requiredSlots?.length ?? ui.questions.length);
  const answeredCount = $derived(Math.max(0, total - ui.questions.length));
  const q = $derived(ui.questions[0] ?? null);
  const slot = $derived(q ? ui.goal?.requiredSlots?.find((s) => s.name === q.slot) : null);

  async function submit() {
    if (!q) return;
    const v = values[q.id];
    if (v === undefined || v === "") return;
    await ui.answerQuestion(q, v);
    values[q.id] = "";
  }

  function chooseBool(v) {
    if (!q) return;
    values[q.id] = v;
    submit();
  }
</script>

{#if !q}
  <div class="space-y-3">
    <div class="rounded-lg border-l-4 border-[color:var(--proven)] bg-muted/40 p-3 text-sm">
      Every question is answered. {#if ui.verdict}The conclusion is above.{:else}Press <b>Run the investigation</b> at the top.{/if}
    </div>
    {#if !ui.verdict}
      <Button size="sm" onclick={() => ui.runInvestigation()}>Run the investigation</Button>
    {/if}
  </div>
{:else}
  <div class="mb-2 flex items-center gap-2">
    <Badge variant="secondary">Question {Math.min(answeredCount + 1, total)} of {total}</Badge>
    {#if q.mandatory}<span class="text-[11px] text-muted-foreground">needed</span>{/if}
    {#if !q.mandatory}<span class="text-[11px] text-muted-foreground">optional</span>{/if}
  </div>

  <div class="rounded-lg border bg-muted/30 p-4">
    <p class="text-base leading-relaxed">{q.text}</p>

    <div class="mt-3 flex items-center gap-2 flex-wrap">
      {#if slot?.type === "bool"}
        <Button size="sm" onclick={() => chooseBool("true")}>Yes</Button>
        <Button size="sm" variant="outline" onclick={() => chooseBool("false")}>No</Button>
      {:else if slot?.type === "num"}
        <Input type="number" class="w-40" placeholder="amount" bind:value={values[q.id]}
               onkeydown={(e) => e.key === "Enter" && submit()} />
        <Button size="sm" onclick={submit}>Save</Button>
      {:else if slot?.type === "date"}
        <Input type="date" class="w-44" bind:value={values[q.id]}
               onkeydown={(e) => e.key === "Enter" && submit()} />
        <Button size="sm" onclick={submit}>Save</Button>
      {:else}
        <Input class="w-72" placeholder="type your answer" bind:value={values[q.id]}
               onkeydown={(e) => e.key === "Enter" && submit()} />
        <Button size="sm" onclick={submit}>Save</Button>
      {/if}
      {#if !q.mandatory}
        <Button variant="ghost" size="sm" onclick={() => ui.dismiss(q)}>
          Skip
        </Button>
      {/if}
    </div>

    {#if q.discriminates?.length}
      <p class="mt-3 text-[11px] text-muted-foreground">
        This answer separates {q.discriminates.length === 1 ? "the explanation still in play" : `${q.discriminates.length} explanations`} —
        it is the question the case most needs right now.
      </p>
    {/if}
  </div>

  {#if ui.questions.length > 1}
    <p class="mt-2 text-xs text-muted-foreground">
      {ui.questions.length - 1} more question{ui.questions.length - 1 === 1 ? "" : "s"} after this.
      Prefer a conversation? Switch to <b>chat</b> above — same questions, same records.
    </p>
  {/if}
{/if}
