<script>
  import { onMount } from "svelte";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/components/ui/card/index.js";
  import { Play, Hammer, Sun, Moon, ListChecks, MessagesSquare, Search, StepForward } from "@lucide/svelte";
  import { ui } from "./lib/store.svelte.js";
  import * as api from "./lib/api.js";
  import Bullseye from "./lib/Bullseye.svelte";
  import HypothesisGraph from "./lib/HypothesisGraph.svelte";
  import Wizard from "./lib/Wizard.svelte";
  import Chat from "./lib/Chat.svelte";
  import ProofPanel from "./lib/ProofPanel.svelte";
  import PacketPreview from "./lib/PacketPreview.svelte";
  import Timeline from "./lib/Timeline.svelte";

  let newCase = $state("");
  let newBundle = $state("bundles/small-business-contract-claim");
  let intentText = $state("");
  // dark-mode toggle: `.dark` class on <html> (Tailwind variant + Skeleton's
  // light-dark()); data-theme stays reserved for the Skeleton preset ("wintry")
  let dark = $state(true);

  onMount(async () => {
    dark = (localStorage.getItem("mode") ?? "dark") === "dark";
    document.documentElement.classList.toggle("dark", dark);
    await ui.refreshCases();
    if (ui.cases.length) await ui.selectCase(ui.cases[0].id);
  });

  function toggleDark() {
    dark = !dark;
    localStorage.setItem("mode", dark ? "dark" : "light");
    document.documentElement.classList.toggle("dark", dark);
  }

  function startIntent() {
    ui.intent = ui.recognizeIntent(intentText);
  }
</script>

<Sidebar.Provider>
  <Sidebar.Root collapsible="icon">
    <Sidebar.Header>
      <div class="flex items-center gap-2 px-2 py-1 font-bold tracking-tight">
        facty<span class="text-primary">.</span>serve
      </div>
    </Sidebar.Header>
    <Sidebar.Content>
      <Sidebar.Group>
        <Sidebar.GroupLabel>Cases</Sidebar.GroupLabel>
        <Sidebar.Menu>
          {#each ui.cases as c}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={ui.case === c.id} onclick={() => ui.selectCase(c.id)}>
                <span class="truncate">{c.id}</span>
              </Sidebar.MenuButton>
            </Sidebar.MenuItem>
          {/each}
        </Sidebar.Menu>
      </Sidebar.Group>
      <Sidebar.Group>
        <Sidebar.GroupLabel>New case</Sidebar.GroupLabel>
        <Sidebar.GroupContent class="flex flex-col gap-2 px-2">
          <Input placeholder="case id" bind:value={newCase} />
          <Input placeholder="bundle dir" bind:value={newBundle} />
          <Button variant="outline" size="sm" onclick={() => ui.op(api.caseInit, newCase, newBundle).then(() => ui.refreshCases())}>init case</Button>
        </Sidebar.GroupContent>
      </Sidebar.Group>
    </Sidebar.Content>
    <Sidebar.Footer>
      <Button variant="ghost" size="sm" class="w-full justify-start" onclick={toggleDark}>
        {#if dark}<Sun class="size-4" /> light{:else}<Moon class="size-4" /> dark{/if}
      </Button>
    </Sidebar.Footer>
  </Sidebar.Root>

  <Sidebar.Inset>
    <header class="flex items-center gap-2 border-b px-3 py-2 flex-wrap sticky top-0 bg-background z-10">
      <Sidebar.Trigger />
      <Separator orientation="vertical" class="h-6" />
      <Input class="w-72" placeholder="intent: “my client won’t pay the invoice”" bind:value={intentText}
             onkeydown={(e) => e.key === "Enter" && startIntent()} />
      <Button variant="ghost" size="sm" onclick={startIntent}><Search class="size-4" /> recognize</Button>
      <div class="flex-1"></div>
      <Button variant={ui.surface === "wizard" ? "secondary" : "ghost"} size="sm" onclick={() => (ui.surface = "wizard")}>
        <ListChecks class="size-4" /> wizard
      </Button>
      <Button variant={ui.surface === "chat" ? "secondary" : "ghost"} size="sm" onclick={() => (ui.surface = "chat")}>
        <MessagesSquare class="size-4" /> chat
      </Button>
      <Button variant="outline" size="sm" onclick={() => ui.op(api.run, ui.case)}><Play class="size-4" /> run engine</Button>
      <Button variant="outline" size="sm" onclick={() => ui.op(api.turn, ui.case, { all: true, surface: ui.surface })}>
        <StepForward class="size-4" /> next turn
      </Button>
      <Button size="sm" onclick={() => ui.op(api.assemble, ui.case)}><Hammer class="size-4" /> assemble</Button>
    </header>

    {#if ui.intent}
      <div class="border-b bg-muted/50 px-4 py-1.5 text-sm">
        intent recognized → <b>{ui.intent.name}</b>
        <span class="text-muted-foreground">({ui.intent.id}, deterministic phrase match; LLM ranked candidates land in Slice 2)</span>
      </div>
    {/if}
    {#if ui.error}
      <div class="border-b bg-destructive/10 px-4 py-1.5 text-sm text-destructive">error: {ui.error}</div>
    {/if}

    <main class="grid grid-cols-1 gap-3 p-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Live state — Proven / Open / Anomalies</CardTitle></CardHeader>
        <CardContent><Bullseye /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Hypothesis graph</CardTitle></CardHeader>
        <CardContent><HypothesisGraph /></CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">
            {ui.surface === "wizard" ? "Questionnaire wizard" : "Chat"}
            <span class="ml-1 normal-case text-muted-foreground">(switchable per turn)</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {#if ui.surface === "wizard"}<Wizard />{:else}<Chat />{/if}
        </CardContent>
        <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Proof tree {#if ui.selected}<span class="normal-case text-muted-foreground">— {ui.selected}</span>{/if}</CardTitle></CardHeader>
        <CardContent><ProofPanel /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Assembled packet</CardTitle></CardHeader>
        <CardContent><PacketPreview /></CardContent>
      </Card>
      <Card class="lg:col-span-2">
        <CardHeader><CardTitle class="text-sm uppercase tracking-wide text-muted-foreground">Turn timeline (branch commits)</CardTitle></CardHeader>
        <CardContent><Timeline /></CardContent>
      </Card>
    </main>
  </Sidebar.Inset>
</Sidebar.Provider>
