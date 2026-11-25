<script>
  import { onDestroy } from "svelte";
  import { forceSimulation, forceX, forceY, forceCollide, forceManyBody } from "d3-force";
  import { ui } from "./store.svelte.js";

  let nodes = $state([]);
  let sim;

  $effect(() => {
    const hyps = ui.byType("Hypothesis");
    const rank = Object.fromEntries(ui.ranking.map((r) => [r.hypothesis, r]));
    // local var: the effect must not read `nodes` (it writes it)
    const ns = hyps.map((h, i) => ({
      id: h.id, status: h.status, prunedBy: h.prunedBy,
      score: rank[h.id]?.score ?? 0, x: 280 + (i - (hyps.length - 1) / 2) * 60, y: 150,
    }));
    if (sim) sim.stop();
    sim = forceSimulation(ns)
      .force("x", forceX(280).strength(0.4))
      .force("y", forceY(150).strength(0.5))
      .force("collide", forceCollide(46))
      .force("charge", forceManyBody().strength(-160))
      .stop();
    for (let i = 0; i < 120; i++) sim.tick();
    nodes = ns;
  });

  onDestroy(() => sim?.stop());

  function color(n) {
    if (n.status === "pruned") return "var(--muted-foreground)";
    return n.id === ui.verdict?.winner ? "var(--proven)" : "var(--open)";
  }
</script>

<svg width="100%" viewBox="0 0 560 300" class="rounded-lg bg-muted/40">
  {#each nodes as n (n.id)}
    <g class="cursor-pointer" onclick={() => ui.selectHypothesis(n.id)}>
      <circle cx={n.x} cy={n.y} r={14 + n.score * 22} fill={color(n)} opacity={n.status === "pruned" ? 0.35 : 0.85}
              stroke={ui.selected === n.id ? "var(--ring)" : "none"} stroke-width="2" />
      <text x={n.x} y={n.y + 4} text-anchor="middle" font-size="11" fill="var(--background)" font-weight="700">{n.id}</text>
      <text x={n.x} y={n.y + 14 + n.score * 22 + 12} text-anchor="middle" font-size="10" class="fill-muted-foreground">
        {n.status === "pruned" ? "ruled out" : `${Math.round(n.score * 100)}% support`}
      </text>
    </g>
  {/each}
</svg>
<div class="mt-1 text-xs text-muted-foreground">Each circle is a possible explanation; size = how strongly the evidence supports it. Click one to see why. Grey = ruled out by the evidence.</div>
