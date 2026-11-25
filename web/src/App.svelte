<script>
  import { onMount } from "svelte";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/components/ui/card/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import {
    Plus, Sun, Moon, MessageSquare, HelpCircle, ArrowRight,
    CheckCircle2, CircleDot, ListChecks, MessagesSquare,
  } from "@lucide/svelte";
  import { ui } from "./lib/store.svelte.js";
  import Bullseye from "./lib/Bullseye.svelte";
  import HypothesisGraph from "./lib/HypothesisGraph.svelte";
  import Wizard from "./lib/Wizard.svelte";
  import Chat from "./lib/Chat.svelte";
  import ProofPanel from "./lib/ProofPanel.svelte";
  import PacketPreview from "./lib/PacketPreview.svelte";
  import Timeline from "./lib/Timeline.svelte";

  let commentOpen = $state(false);
  let helpOpen = $state(false);
  let pickerOpen = $state(false);
  let commentText = $state("");
  let tab = $state("investigate");
  let exampleEvidence = $state(true);
  let dark = $state(true);

  onMount(async () => {
    dark = (localStorage.getItem("mode") ?? "dark") === "dark";
    document.documentElement.classList.toggle("dark", dark);
    await Promise.all([ui.refreshBundles(), ui.refreshCases()]);
    const remembered = localStorage.getItem("case");
    const first = ui.cases.find((c) => c.id === remembered) || ui.cases[0];
    if (first) await ui.selectCase(first.id);
  });

  function toggleDark() {
    dark = !dark;
    localStorage.setItem("mode", dark ? "dark" : "light");
    document.documentElement.classList.toggle("dark", dark);
  }

  async function pick(caseId) {
    localStorage.setItem("case", caseId);
    await ui.selectCase(caseId);
  }

  // The one button a person in a hurry needs: it always does the next thing.
  const primary = $derived.by(() => {
    if (!ui.case) return { label: "Start an investigation", act: () => (pickerOpen = true) };
    if (ui.questions.length) return { label: "Answer the questions", act: () => (tab = "investigate") };
    if (!ui.verdict) return { label: "Run the investigation", act: () => ui.runInvestigation() };
    if (!ui.byType("AssembledDocument")[0]) return { label: "Build the document", act: () => ui.buildDocument() };
    return { label: "Print / save PDF", act: () => window.print() };
  });

  const statusChip = $derived.by(() => {
    if (!ui.case) return { text: "no case yet", tone: "outline" };
    if (ui.questions.length) return { text: "needs your answers", tone: "secondary" };
    if (!ui.verdict) return { text: "ready to run", tone: "default" };
    if (!ui.byType("AssembledDocument")[0]) return { text: "conclusion reached", tone: "default" };
    return { text: "document ready", tone: "default" };
  });
</script>

<Sidebar.Provider>
  <Sidebar.Root collapsible="icon">
    <Sidebar.Header>
      <div class="flex flex-col px-2 py-1">
        <div class="font-bold tracking-tight text-lg leading-none">facty<span class="text-primary">.</span></div>
        <div class="text-[11px] text-muted-foreground">deterministic investigations</div>
      </div>
    </Sidebar.Header>
    <Sidebar.Content>
      <Sidebar.Group>
        <Sidebar.GroupContent class="px-2 pb-1">
          <Button class="w-full justify-start" onclick={() => (pickerOpen = true)}>
            <Plus class="size-4" /> New investigation
          </Button>
        </Sidebar.GroupContent>
      </Sidebar.Group>
      <Sidebar.Group>
        <Sidebar.GroupLabel>Your investigations</Sidebar.GroupLabel>
        <Sidebar.Menu>
          {#each ui.cases as c}
            {@const info = ui.caseInfo[c.id]}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={ui.case === c.id} class="h-auto items-start py-1.5" onclick={() => pick(c.id)}>
                {#if info?.done}
                  <CheckCircle2 class="size-4 text-[color:var(--proven)]" />
                {:else}
                  <CircleDot class="size-4 text-muted-foreground" />
                {/if}
                <div class="flex min-w-0 flex-col items-start">
                  <span class="w-full line-clamp-2 text-[13px] leading-tight" title={info?.title || c.id}>{info?.title || c.id}</span>
                  <span class="text-[11px] text-muted-foreground">
                    {info?.open ? `${info.open} question${info.open === 1 ? "" : "s"} left` : info?.done ? "document ready" : "in progress"}
                  </span>
                </div>
              </Sidebar.MenuButton>
            </Sidebar.MenuItem>
          {:else}
            <div class="px-2 py-2 text-xs text-muted-foreground">nothing yet — start one above</div>
          {/each}
        </Sidebar.Menu>
      </Sidebar.Group>
    </Sidebar.Content>
    <Sidebar.Footer>
      <Button variant="ghost" size="sm" class="w-full justify-start" onclick={toggleDark}>
        {#if dark}<Sun class="size-4" /> light{:else}<Moon class="size-4" /> dark{/if}
      </Button>
    </Sidebar.Footer>
  </Sidebar.Root>

  <Sidebar.Inset class="min-w-0 overflow-x-hidden">
    <header class="flex items-center gap-2 border-b px-3 py-2 sticky top-0 bg-background z-10">
      <Sidebar.Trigger />
      <Separator orientation="vertical" class="h-6" />
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <h1 class="truncate text-sm font-semibold">{ui.title || "Pick an investigation"}</h1>
          <Badge variant={statusChip.tone} class="shrink-0">{statusChip.text}</Badge>
        </div>
        <div class="text-[11px] text-muted-foreground truncate">{ui.headline}</div>
      </div>
      <div class="flex-1"></div>
      <Button size="sm" onclick={primary.act}><ArrowRight class="size-4" /> {primary.label}</Button>
      <Dialog.Root bind:open={helpOpen}>
        <Dialog.Trigger>
          <Button variant="ghost" size="sm"><HelpCircle class="size-4" /> how this works</Button>
        </Dialog.Trigger>
        <Dialog.Content class="max-w-lg">
          <Dialog.Header>
            <Dialog.Title>How this works</Dialog.Title>
            <Dialog.Description>Three steps, no AI in the decision.</Dialog.Description>
          </Dialog.Header>
          <div class="space-y-3 text-sm">
            <p><b>1. Answer a few questions.</b> Only what the case still needs — everything else is read from the documents.</p>
            <p><b>2. Press “Run the investigation”.</b> A fixed set of rules checks the evidence and sorts the possible explanations. It is the same answer every time, and the reasoning is kept.</p>
            <p><b>3. Build the document.</b> Only the parts the evidence proves are included. Print it or save it as a PDF.</p>
            <p><b>The three rings</b> show where you stand: <span class="font-medium" style="color: var(--proven)">inner = proven</span>, <span class="font-medium" style="color: var(--open)">middle = still open</span>, <span class="font-medium" style="color: var(--anomaly)">outer = doesn't fit</span>.</p>
            <p class="text-muted-foreground">The <b>Details</b> tab holds the audit trail — every conclusion there traces back to a document and a rule. Leave a comment with the <MessageSquare class="inline size-3" /> button on any screen; it is stored with the case.</p>
          </div>
        </Dialog.Content>
      </Dialog.Root>
      <Dialog.Root bind:open={commentOpen}>
        <Dialog.Trigger>
          <Button variant="ghost" size="sm">
            <MessageSquare class="size-4" /> comment
            {#if ui.feedback.length}<Badge variant="secondary" class="ml-1">{ui.feedback.length}</Badge>{/if}
          </Button>
        </Dialog.Trigger>
        <Dialog.Content class="max-w-lg">
          <Dialog.Header>
            <Dialog.Title>Leave a comment on this screen</Dialog.Title>
            <Dialog.Description>Saved with the case — the team reads these with <code>facty feedback list</code>.</Dialog.Description>
          </Dialog.Header>
          <Textarea bind:value={commentText} placeholder="what's confusing, missing, or wrong here?" rows={4} />
          <Dialog.Footer>
            <Button size="sm" disabled={!commentText.trim()}
                    onclick={() => { ui.addFeedback(commentText, `case:${ui.case} surface:${tab}`); commentText = ""; commentOpen = false; }}>
              Save comment
            </Button>
          </Dialog.Footer>
        </Dialog.Content>
      </Dialog.Root>
    </header>

    {#if ui.error}
      <div class="border-b bg-destructive/10 px-4 py-1.5 text-sm text-destructive">
        That didn't work — {ui.error}
      </div>
    {/if}
    {#if ui.notice}
      <div class="border-b bg-primary/10 px-4 py-1.5 text-sm">{ui.notice}</div>
    {/if}

    {#if !ui.case}
      <main class="p-6">
        <Card>
          <CardHeader><CardTitle>Start with the situation, not the software</CardTitle></CardHeader>
          <CardContent class="space-y-4">
            <p class="text-sm text-muted-foreground">
              Each investigation is a short list of questions and a document at the end.
              Pick the one that sounds like your problem.
            </p>
            <div class="grid gap-3 sm:grid-cols-3">
              {#each ui.bundles.filter((b) => b.title) as b}
                <button class="rounded-lg border p-4 text-left hover:bg-muted/60"
                        onclick={() => ui.startCase(b, { withExample: true })}>
                  <div class="text-sm font-semibold">{b.title}</div>
                  <div class="mt-1 text-xs text-muted-foreground line-clamp-3">{b.statement}</div>
                  <div class="mt-2 text-xs text-primary">Start →</div>
                </button>
              {/each}
            </div>
          </CardContent>
        </Card>
      </main>
    {:else}
      <Tabs.Root bind:value={tab} class="flex-col px-4 pt-3">
        <Tabs.List>
          <Tabs.Trigger value="investigate">Investigate</Tabs.Trigger>
          <Tabs.Trigger value="document">Document</Tabs.Trigger>
          <Tabs.Trigger value="details">Details</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="investigate" class="pt-3">
          <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Card class="lg:col-span-2">
              <CardHeader>
                <CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Where this stands</CardTitle>
              </CardHeader>
              <CardContent class="space-y-3">
                {#if ui.conclusion}
                  <div class="rounded-lg border-l-4 border-[color:var(--proven)] bg-muted/40 p-3">
                    <div class="text-xs uppercase tracking-wide text-muted-foreground">Conclusion</div>
                    <p class="mt-1 text-sm">{ui.conclusion.statement}</p>
                    <div class="mt-1 text-xs text-muted-foreground">
                      backed by {ui.conclusion.support} independent check{ui.conclusion.support === 1 ? "" : "s"}
                      {#if ui.ruledOut.length} · {ui.ruledOut.length} alternative{ui.ruledOut.length === 1 ? "" : "s"} ruled out{/if}
                    </div>
                  </div>
                {:else if ui.questions.length}
                  <p class="text-sm text-muted-foreground">Answer the questions below and the conclusion appears here.</p>
                {:else}
                  <p class="text-sm text-muted-foreground">Everything needed is in — press <b>Run the investigation</b> above.</p>
                {/if}

                {#if ui.ruledOut.length}
                  <details class="text-sm">
                    <summary class="cursor-pointer text-muted-foreground">What the evidence rules out</summary>
                    <ul class="mt-2 space-y-2">
                      {#each ui.ruledOut as r}
                        <li class="rounded-md border p-2">
                          <div class="text-xs text-muted-foreground line-through">{r.statement}</div>
                          <div class="mt-1 text-xs">{r.why}</div>
                        </li>
                      {/each}
                    </ul>
                  </details>
                {/if}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Your picture</CardTitle></CardHeader>
              <CardContent><Bullseye /></CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div class="flex items-center gap-2 flex-wrap">
                  <CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">
                    {ui.surface === "wizard" ? "Questions" : "Chat"}
                  </CardTitle>
                  <div class="flex-1"></div>
                  <Button variant={ui.surface === "wizard" ? "secondary" : "ghost"} size="sm" onclick={() => (ui.surface = "wizard")}>
                    <ListChecks class="size-4" /> one at a time
                  </Button>
                  <Button variant={ui.surface === "chat" ? "secondary" : "ghost"} size="sm" onclick={() => (ui.surface = "chat")}>
                    <MessagesSquare class="size-4" /> chat
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {#if ui.surface === "wizard"}<Wizard />{:else}<Chat />{/if}
              </CardContent>
            </Card>
          </div>
        </Tabs.Content>

        <Tabs.Content value="document" class="pt-3">
          <Card>
            <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Your document</CardTitle></CardHeader>
            <CardContent><PacketPreview /></CardContent>
          </Card>
        </Tabs.Content>

        <Tabs.Content value="details" class="pt-3">
          <p class="mb-3 text-xs text-muted-foreground">
            The audit trail. Everything here is the same for a rerun: rules, proofs and step log.
            Nothing in this tab is needed to use the case.
          </p>
          <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Possible explanations</CardTitle></CardHeader>
              <CardContent><HypothesisGraph /></CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">
                  Why a conclusion holds {#if ui.selected}<span class="normal-case text-muted-foreground">— {ui.selected}</span>{/if}
                </CardTitle>
              </CardHeader>
              <CardContent><ProofPanel /></CardContent>
            </Card>
            <Card class="lg:col-span-2">
              <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Step log (saved with the case)</CardTitle></CardHeader>
              <CardContent><Timeline /></CardContent>
            </Card>
          </div>
        </Tabs.Content>
      </Tabs.Root>
    {/if}
  </Sidebar.Inset>
</Sidebar.Provider>

{#if pickerOpen}
<Dialog.Root bind:open={pickerOpen}>
  <Dialog.Content class="max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>New investigation</Dialog.Title>
      <Dialog.Description>Pick the situation that sounds like yours. Each one is a signed, standard set of rules — the same answers every time.</Dialog.Description>
    </Dialog.Header>
    <div class="grid gap-2">
      {#each ui.bundles.filter((b) => b.title) as b}
        <button class="rounded-lg border p-3 text-left hover:bg-muted/60"
                onclick={() => { pickerOpen = false; ui.startCase(b, { withExample: exampleEvidence }); }}>
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-semibold">{b.title}</span>
            <span class="text-[11px] text-muted-foreground">v{b.version}</span>
          </div>
          <div class="mt-1 text-xs text-muted-foreground line-clamp-2">{b.statement}</div>
          {#if b.output}<div class="mt-1 text-[11px] text-primary">You get: {b.output}</div>{/if}
        </button>
      {/each}
    </div>
    <label class="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
      <input type="checkbox" bind:checked={exampleEvidence} />
      start with the example evidence (so you can try it immediately)
    </label>
  </Dialog.Content>
</Dialog.Root>
{/if}
