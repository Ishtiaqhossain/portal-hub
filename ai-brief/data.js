/*
 * The AI Brief — sample edition content.
 *
 * This is hand-written SAMPLE content used to demonstrate the product. It is
 * illustrative, not live reporting. Wire `window.EDITION` to a real digest
 * generator (RSS pull + LLM summarization) to make it a live daily brief.
 *
 * Data is attached to `window` (not fetched) so the site works when opened
 * directly via file:// as well as when served over HTTP. Zero dependencies.
 */
window.EDITION = {
  masthead: "The AI Brief",
  tagline: "Daily intelligence on AI agents, coding tools, model releases, and AI-native engineering.",
  date: "Monday, June 29, 2026",
  editionLabel: "Today’s Edition",
  sample: true,

  // ── Story bank ──────────────────────────────────────────────────────────
  // Every card on the site references one of these by id. Each story carries
  // the full article structure (What happened / Why it matters / Skeptical
  // read / …) plus a Signal score and per-persona implications.
  stories: {
    "agent-runtime": {
      id: "agent-runtime",
      kicker: "Agents",
      headline: "OpenAI ships an agent runtime, turning agents into infrastructure",
      takeaway: "Agent platforms are quietly becoming the new application server — and the big labs now want to own that layer.",
      summary: "A managed runtime for long-running, tool-using agents with built-in state, retries, and governance.",
      readTime: 4,
      signal: { signal: "High", novelty: "Medium", practical: "High", hype: "Medium" },
      whatHappened:
        "OpenAI introduced a hosted runtime for long-running agents: durable execution, automatic retries, a tool/permission broker, per-step tracing, and budget caps. Agents are defined as code, deployed once, and run as managed services rather than as scripts babysat by a human.",
      whatChanged:
        "Until now, ‘agent frameworks’ were libraries you ran yourself — you owned the queue, the retries, the observability, and the 3am pages. Moving that into a managed runtime reframes the agent as a deployable unit of infrastructure, the way containers reframed the process.",
      whyItMatters:
        "Whoever owns the runtime owns the defaults: how tools are authorized, how spend is capped, where traces land, what ‘safe’ means. That is platform power. For teams, it removes the least glamorous 60% of agent engineering — the plumbing — which is exactly the part that has kept agents stuck in demos.",
      whoShouldCare: ["Engineering Leader", "Founder", "Developer", "Investor"],
      skepticalRead:
        "Durable execution is a solved idea (Temporal, Inngest, Step Functions) wearing an agent hat; the novelty is packaging plus model lock-in, not computer science. Managed runtimes also mean your control loop lives on someone else’s servers with their kill switch and their pricing. ‘Governance’ here is mostly logging and budget caps — useful, but not the security model an enterprise platform team will actually require.",
      sources: [
        { title: "OpenAI — Agent runtime announcement (sample)", url: "#" },
        { title: "Docs: durable agents & tool broker (sample)", url: "#" },
      ],
      related: [
        { label: "Compare: LangGraph vs CrewAI vs AutoGen", href: "#compare" },
        { label: "Timeline: AI coding agents 2023–2026", href: "#timeline" },
        { label: "Repo: open-source agent runtime", href: "article.html?id=&" },
      ],
      personas: {
        "Engineering Leader":
          "Treat this as a build-vs-buy fork for your agent platform. The runtime erases your plumbing backlog but hands the vendor your authorization model and a kill switch. Pilot it for one non-critical workflow; keep the tool-permission broker abstracted behind your own interface so you can swap runtimes later.",
        "Founder":
          "The infra layer just got colonized by a model lab. If your startup IS the runtime, your moat is now neutrality (multi-model) and depth (governance, eval, audit) the lab won’t prioritize. If you build ON agents, this is a tailwind — less to operate.",
        "Developer":
          "You can delete a lot of retry/queue/trace code. The trade is less control over the loop and a new proprietary deploy target to learn. Prototype against it, but keep your agent logic framework-agnostic.",
        "Researcher":
          "Standardized runtimes make agent behavior more reproducible and instrumentable — per-step traces are a gift for eval work. Watch whether the runtime’s defaults bias which agent architectures people even try.",
        "Investor":
          "Classic platform land-grab: own the runtime, own the margin. Re-underwrite agent-infra startups on whether they’re differentiated (neutral, governed, observable) or about to be commoditized by a lab’s free tier.",
        "Product Manager":
          "Lower operational cost for agentic features means faster shipping, but you inherit the runtime’s limits on latency, tool access, and data residency. Get those constraints on the table before you scope.",
      },
    },

    "claude-code-team": {
      id: "claude-code-team",
      kicker: "Coding",
      headline: "Claude Code adds repo-level team workflows",
      takeaway: "Agentic coding is moving from a solo power tool to a team workflow layer.",
      summary: "Anthropic expanded Claude Code with shared repo context, review handoffs, and team policy controls.",
      readTime: 3,
      signal: { signal: "High", novelty: "Medium", practical: "High", hype: "Low" },
      whatHappened:
        "Claude Code gained team-oriented features: shared repository context, agent-to-human review handoffs, org-level permission policies, and an audit trail of what the agent changed and why.",
      whatChanged:
        "The unit of use shifts from ‘one developer + one agent in a terminal’ to ‘a team sharing agents, context, and guardrails across a repo.’ That makes agentic coding a thing platform teams provision, not just a thing individuals install.",
      whyItMatters:
        "Team features are where developer tools turn into platform revenue and where governance lives. Once the agent leaves changes with provenance and policy, it can plausibly touch shared codebases — the gate that has kept agentic coding mostly in side projects.",
      whoShouldCare: ["Engineering Leader", "Developer", "Product Manager"],
      skepticalRead:
        "‘Team workflow’ features can be lipstick on a single-player tool: shared context without shared accountability just spreads blast radius. The hard problems — merge conflicts between agents, who owns an agent’s bad PR, eval gates before merge — are organizational, and a feature flag doesn’t solve them.",
      sources: [
        { title: "Anthropic — Claude Code team features (sample)", url: "#" },
        { title: "Docs: org policies & audit trail (sample)", url: "#" },
      ],
      related: [
        { label: "Compare: Claude Code vs Cursor vs Codex-style agents", href: "#compare" },
        { label: "Benchmark Watch: SWE-bench movement", href: "article.html?id=swe-bench" },
      ],
      personas: {
        "Engineering Leader":
          "This is the feature set that lets you actually roll agentic coding out org-wide: policy, provenance, audit. Stand up a paved-road config, define merge-gate evals, and decide who owns an agent’s PR before you broaden access — the tooling won’t answer that for you.",
        "Founder":
          "Validation that the value is in the team/governance layer, not the autocomplete. If you’re in dev-tools, compete on the workflow and policy surface, not raw completion quality.",
        "Developer":
          "Shared context cuts onboarding and review friction, but expect more process around agent changes. Learn the audit/handoff flow — it’s how you keep agent PRs reviewable.",
        "Researcher":
          "Audit trails of ‘what the agent changed and why’ are a useful corpus for studying agent reliability and human-agent handoff in the wild.",
        "Investor":
          "Team tier = expansion revenue and stickiness. The signal to watch is seat-to-org conversion and whether governance features command a premium.",
        "Product Manager":
          "Provenance and policy unblock agentic features for regulated/shared codebases. Scope the rollout around review gates and clear ownership, not just ‘turn it on.’",
      },
    },

    "gemini-bench": {
      id: "gemini-bench",
      kicker: "Models",
      headline: "Gemini posts a record on a long-context tool-use benchmark",
      takeaway: "A headline benchmark jumped — the open question is whether it reflects real multi-step work.",
      summary: "A new frontier Gemini result tops a long-context, tool-use eval; independent verification is pending.",
      readTime: 3,
      signal: { signal: "Medium", novelty: "Medium", practical: "Medium", hype: "High" },
      whatHappened:
        "Google reported a state-of-the-art score on a long-context benchmark that mixes retrieval, tool calls, and multi-step reasoning, claiming a clear margin over prior frontier models.",
      whatChanged:
        "The leaderboard reshuffled at the top, and the gap is concentrated in long-context tool use — the regime that matters most for agents, rather than single-turn Q&A.",
      whyItMatters:
        "If the gain holds up out of distribution, it lowers the failure rate of long agent runs, which is the thing that actually breaks production agents. If it doesn’t, it’s a leaderboard artifact that won’t survive contact with your workload.",
      whoShouldCare: ["Engineering Leader", "Researcher", "Developer", "Investor"],
      skepticalRead:
        "Single-vendor, single-benchmark, no independent replication yet — the textbook setup for a number that doesn’t generalize. Long-context benchmarks are easy to saturate and easy to teach to. Until a third party reproduces it on tasks you didn’t train on, treat the margin as marketing, not capability.",
      sources: [
        { title: "Google — Gemini benchmark report (sample)", url: "#" },
        { title: "Benchmark methodology (sample)", url: "#" },
      ],
      related: [
        { label: "Benchmark Watch: is this saturated?", href: "article.html?id=swe-bench" },
        { label: "Compare: OpenAI vs Anthropic vs Gemini for tool use", href: "#compare" },
      ],
      personas: {
        "Engineering Leader":
          "Don’t reprioritize a model migration on one vendor benchmark. Run it on your own eval set with your tools and your long contexts before you believe the margin.",
        "Founder":
          "Frontier parity keeps shifting; design for model-swappability so a leaderboard move is a config change, not a rewrite.",
        "Developer":
          "Interesting if your agents do long, tool-heavy runs. Verify on your tasks — long-context scores rarely transfer cleanly.",
        "Researcher":
          "Prime candidate for independent replication and contamination analysis. The methodology, not the headline, is the story.",
        "Investor":
          "Benchmark leapfrogging is now monthly and mean-reverting. Weight durable distribution and switching costs over any single SOTA claim.",
        "Product Manager":
          "Could improve reliability of long workflows — if it holds. Gate any model switch on your own quality bar, not the press release.",
      },
    },

    "meta-oss-agents": {
      id: "meta-oss-agents",
      kicker: "Models",
      headline: "Meta open-sources a family of agent-tuned models",
      takeaway: "Open weights tuned for tool use put credible agent models on infrastructure you control.",
      summary: "A permissively licensed model family tuned specifically for tool-calling and multi-step agent loops.",
      readTime: 3,
      signal: { signal: "High", novelty: "Medium", practical: "High", hype: "Medium" },
      whatHappened:
        "Meta released open-weight models tuned for tool calling and agentic loops under a permissive license, with reference harnesses for common agent patterns.",
      whatChanged:
        "Agent-grade tool use stops being a closed-API-only capability. You can run a competent tool-calling model on your own infrastructure, with your own data boundary.",
      whyItMatters:
        "Data residency, cost at scale, and no per-token vendor tax are exactly the blockers that stall enterprise agent rollouts. Open weights tuned for tool use attack all three at once.",
      whoShouldCare: ["Engineering Leader", "Developer", "Researcher", "Founder"],
      skepticalRead:
        "Open weights aren’t free: you inherit serving, scaling, safety tuning, and eval. ‘Permissive’ licenses often carry usage caveats worth a lawyer’s read. And tool-use tuning on benchmarks doesn’t guarantee robustness on your messy internal tools.",
      sources: [
        { title: "Meta — open agent models (sample)", url: "#" },
        { title: "Model card & license (sample)", url: "#" },
      ],
      related: [
        { label: "Builder Radar: self-hosted serving stacks", href: "#radar" },
        { label: "AI Company Map: Foundation models", href: "#map" },
      ],
      personas: {
        "Engineering Leader":
          "This is your lever for cost and data-residency control. Stand up a serving stack and eval harness; compare total cost of ownership (GPU + ops) against the API tax honestly before committing.",
        "Founder":
          "Open agent weights compress the moat of closed-model wrappers. Differentiate on workflow, data, and evals — not on having access to a good tool-calling model.",
        "Developer":
          "You can now run agents fully in-house for sensitive data. Budget real time for serving and eval — the model is the easy part.",
        "Researcher":
          "Open agent-tuned weights are a research accelerant — you can probe, fine-tune, and ablate the tool-use behavior directly.",
        "Investor":
          "Each capable open release compresses closed-model pricing power and lifts the agent-infra/ops layer. Reweight accordingly.",
        "Product Manager":
          "Enables on-prem / data-resident agent features for regulated customers. Factor in the ops cost — it changes unit economics and SLAs.",
      },
    },

    "mcp-registry": {
      id: "mcp-registry",
      kicker: "Infra",
      headline: "MCP servers get a registry and a security profile",
      takeaway: "MCP is hardening from a clever idea into the connective tissue between agents and tools — and the new API layer.",
      summary: "A discovery registry plus signed-server and scoped-permission conventions arrive for the Model Context Protocol.",
      readTime: 3,
      signal: { signal: "High", novelty: "High", practical: "High", hype: "Medium" },
      whatHappened:
        "The MCP ecosystem added a server registry for discovery and a security profile: signed servers, scoped permissions, and capability declarations agents can reason about before connecting.",
      whatChanged:
        "MCP moves from ‘point an agent at a local server’ to a discoverable, verifiable network of capabilities — the difference between a clever protocol and an actual integration layer.",
      whyItMatters:
        "If MCP becomes the standard way agents reach tools and data, the registry is the new package index and the security profile is the new OAuth. That’s where ecosystems and lock-in form.",
      whoShouldCare: ["Engineering Leader", "Developer", "Founder", "Investor"],
      skepticalRead:
        "Registries invite the npm failure modes: typosquatting, abandoned servers, supply-chain risk — now with an agent that can take actions on your behalf. Signing helps but doesn’t establish trust in what a server actually does. ‘Scoped permissions’ are only as good as the agent’s discipline in requesting the minimum, which today it does not have.",
      sources: [
        { title: "MCP registry & security profile (sample)", url: "#" },
        { title: "Spec: signed servers and scopes (sample)", url: "#" },
      ],
      related: [
        { label: "Deep Dive: why MCP servers are the new API layer", href: "article.html?id=deep-dive" },
        { label: "Agent Watch: MCP servers", href: "#agentwatch" },
      ],
      personas: {
        "Engineering Leader":
          "Get ahead of shadow-MCP: agents wiring themselves to unvetted servers is a real exfiltration path. Stand up an allowlisted internal registry and require signed, scoped servers before this proliferates.",
        "Founder":
          "The registry + security layer is a platform opportunity — trust, curation, and audit for MCP is a business closed labs won’t prioritize. Move early.",
        "Developer":
          "Discovery makes wiring tools far easier, but treat third-party MCP servers like dependencies you’d audit. Prefer signed, minimally-scoped servers.",
        "Researcher":
          "A standard capability layer makes agent behavior comparable across tools — useful for systematic tool-use evaluation.",
        "Investor":
          "Watch who owns discovery and trust for MCP. The registry layer is a classic toll-booth if a credible neutral party takes it.",
        "Product Manager":
          "Faster integrations via MCP, but new third-party risk. Bake server vetting and scoped permissions into your security review.",
      },
    },

    "ai-layoffs": {
      id: "ai-layoffs",
      kicker: "Startups",
      headline: "Funding rotates toward agent infrastructure as wrappers consolidate",
      takeaway: "Capital is moving from thin model wrappers to the infra, eval, and governance layers underneath agents.",
      summary: "A megaround for an agent-infra company, two acqui-hires of wrapper startups, and targeted layoffs at a chat-first vendor.",
      readTime: 3,
      signal: { signal: "Medium", novelty: "Low", practical: "Medium", hype: "Medium" },
      whatHappened:
        "An agent-infrastructure company raised a large round; two thin-wrapper startups were acqui-hired; and a chat-first AI vendor cut staff while repositioning toward enterprise workflows.",
      whatChanged:
        "The market is repricing: undifferentiated wrappers are consolidating, while infra, eval, and governance — the unglamorous layers — attract the capital.",
      whyItMatters:
        "Where money flows shapes which tools you’ll be integrating in 18 months. The rotation says durable value is accruing below the application layer.",
      whoShouldCare: ["Investor", "Founder", "Engineering Leader"],
      skepticalRead:
        "One megaround and a couple of acqui-hires is a vibe, not a trend. ‘Infra over wrappers’ is also a convenient narrative for funds already long on infra. Layoffs framed as ‘repositioning’ are often just layoffs.",
      sources: [
        { title: "Funding round coverage (sample)", url: "#" },
        { title: "Acqui-hire and restructuring notes (sample)", url: "#" },
      ],
      related: [
        { label: "AI Company Map: Agent infra", href: "#map" },
        { label: "Deep Dive: the race to own the coding workflow", href: "article.html?id=deep-dive" },
      ],
      personas: {
        "Engineering Leader":
          "Vendor risk signal: thin-wrapper tools in your stack may get acquired or sunset. Favor vendors with a real infra/governance moat for anything load-bearing.",
        "Founder":
          "If you’re a wrapper, the window to differentiate (data, workflow, distribution) is closing. If you’re infra, capital is with you — spend it on durable moat, not logos.",
        "Developer":
          "Expect churn in the tool list. Keep integrations behind interfaces so a vendor change isn’t a rewrite.",
        "Researcher":
          "Funding rotation toward eval/governance means more industry demand (and data) for rigorous agent evaluation work.",
        "Investor":
          "The rotation is the story — but check your own bias. Underwrite on differentiation and switching costs, not the ‘infra > wrappers’ slogan.",
        "Product Manager":
          "Reassess build-on-vendor bets for staying power. Have a migration path for anything depending on a thin-wrapper startup.",
      },
    },

    "swe-bench": {
      id: "swe-bench",
      kicker: "Research",
      headline: "SWE-bench gains contamination controls as scores cluster near the top",
      takeaway: "The field’s favorite coding benchmark is showing saturation — so the maintainers changed the test, not the models.",
      summary: "A refreshed SWE-bench split with held-out, post-cutoff issues to fight contamination and re-separate the leaders.",
      readTime: 4,
      signal: { signal: "High", novelty: "Medium", practical: "High", hype: "Low" },
      whatHappened:
        "Maintainers released a refreshed SWE-bench split built from recent, post-training-cutoff issues with stricter contamination controls, after top systems clustered within a few points of each other.",
      whatChanged:
        "When everyone scores ~the same, the benchmark stops discriminating. The fix re-establishes a gap using tasks the models couldn’t have memorized.",
      whyItMatters:
        "SWE-bench is a primary signal for buying and building decisions in agentic coding. If it’s saturated or contaminated, those decisions rest on noise. A credible refresh restores a usable signal — and resets the leaderboard.",
      whoShouldCare: ["Engineering Leader", "Researcher", "Developer", "Investor"],
      skepticalRead:
        "Even a refreshed SWE-bench is GitHub-issue-shaped work, which is a narrow slice of real engineering — no design, no ambiguity, no stakeholders. A high score still doesn’t mean the agent can land a feature in your codebase. Treat it as a regression signal, not a competence certificate.",
      sources: [
        { title: "SWE-bench refreshed split (sample)", url: "#" },
        { title: "Contamination methodology (sample)", url: "#" },
      ],
      related: [
        { label: "Benchmark Watch (full section)", href: "#benchmark" },
        { label: "Compare: coding agents head-to-head", href: "#compare" },
      ],
      personas: {
        "Engineering Leader":
          "Re-baseline your internal coding-agent eval against the refreshed split, and keep your own private held-out tasks — that’s the only score that reflects your codebase. Don’t buy on the public leaderboard alone.",
        "Founder":
          "A reshuffled leaderboard is a marketing opening if you place well — but customers increasingly run private evals. Invest in real-task performance over benchmark gaming.",
        "Developer":
          "Useful as a regression signal across model versions. Remember it tests issue-resolution, not design or ambiguity.",
        "Researcher":
          "The contamination methodology is the contribution worth reading. Adopt held-out, post-cutoff splits as standard practice.",
        "Investor":
          "Discount pitches leaning on saturated benchmarks. Reward teams that evaluate on contamination-controlled, real-world tasks.",
        "Product Manager":
          "Don’t set roadmap expectations from a single benchmark. Validate agent coding features on representative tasks from your own backlog.",
      },
    },

    "deep-dive": {
      id: "deep-dive",
      kicker: "Weekly Deep Dive",
      headline: "Why MCP servers are becoming the new API layer",
      takeaway: "The integration surface for AI is shifting from human-designed REST endpoints to agent-discoverable capabilities — and that rewires who holds power in the stack.",
      summary: "A Sunday read on how the Model Context Protocol is turning into the connective tissue of AI-native software.",
      readTime: 9,
      signal: { signal: "High", novelty: "High", practical: "Medium", hype: "Medium" },
      whatHappened:
        "Over the past year, MCP went from a clever way to feed context to one model to a broad convention for exposing tools, data, and actions to any agent — and this week it gained a registry and a security profile (signed servers, scoped permissions). The pieces of an ecosystem are now visibly assembling.",
      whatChanged:
        "Classic APIs are designed for human developers who read docs and write integration code. MCP servers are designed for agents that discover capabilities at runtime and decide which to use. The consumer of the interface changed from a person to a model — and interfaces reshape themselves around their consumer.",
      whyItMatters:
        "If agents become a primary way software is operated, the MCP server — not the REST endpoint — becomes the unit of integration. That moves leverage toward whoever owns discovery (the registry), trust (signing), and the highest-value capability servers. It also changes how you design internal platforms: you start shipping MCP servers for your own systems so your agents (and maybe partners’) can use them safely.",
      whoShouldCare: ["Engineering Leader", "Founder", "Developer", "Investor", "Product Manager"],
      skepticalRead:
        "Protocols win on adoption, not elegance, and we’ve watched plenty of ‘universal’ layers (SOAP, semantic web, a dozen plugin standards) never reach escape velocity. MCP’s security story is early — a registry of action-taking servers an agent can invoke is a genuinely new attack surface, and ‘scoped permissions’ lean on agent discipline that doesn’t exist yet. The honest read: MCP is the front-runner for the agent-tool interface, but ‘new API layer’ is a destination, not a fact, and the security model has to mature before serious enterprises route real actions through it.",
      sources: [
        { title: "MCP registry & security profile (sample)", url: "#" },
        { title: "A year of MCP adoption (sample)", url: "#" },
        { title: "Spec & scoped permissions (sample)", url: "#" },
      ],
      related: [
        { label: "MCP servers get a registry (today’s story)", href: "article.html?id=mcp-registry" },
        { label: "Agent Watch: MCP servers", href: "index.html#agentwatch" },
        { label: "AI Company Map: Agent infra", href: "index.html#map" },
      ],
      personas: {
        "Engineering Leader":
          "Start treating internal MCP servers as a platform deliverable: a curated, signed, scoped catalog of your systems’ capabilities is how you let agents act safely. The registry/trust decisions you make now are hard to reverse later.",
        "Founder":
          "The neutral trust-and-discovery layer for MCP is an open lane the big labs won’t want to own (neutrality is the product). So is a deep, well-governed server for a high-value vertical system.",
        "Developer":
          "Learn to author MCP servers, not just consume them — it’s becoming a core integration skill. Design for least privilege from day one.",
        "Researcher":
          "A standard capability interface makes agent tool-use measurable and comparable. The security profile is also a rich research target — scoped-permission enforcement is unsolved.",
        "Investor":
          "Map the MCP stack like the early API economy: discovery, trust, high-value servers, observability. The toll-booth positions are discovery and trust.",
        "Product Manager":
          "If your product exposes data or actions, an MCP server may become table stakes for being usable by agents. Weigh that against the new third-party risk it introduces.",
      },
    },
  },

  // ── Front-page layout (references story ids) ────────────────────────────
  lead: "agent-runtime",

  // “The 5 Things That Matter” — the daily executive summary.
  fiveThings: [
    { id: "meta-oss-agents", label: "New model release", note: "Open agent-tuned weights you can self-host." },
    { id: "swe-bench", label: "Important benchmark result", note: "SWE-bench refresh fights saturation & contamination." },
    { id: "claude-code-team", label: "New coding-agent capability", note: "Claude Code goes team-wide with policy + audit." },
    { id: "mcp-registry", label: "Notable research/standard", note: "MCP gets a registry and a security profile." },
    { id: "ai-layoffs", label: "Market / company move", note: "Capital rotates from wrappers to agent infra." },
  ],

  sections: {
    top: ["claude-code-team", "gemini-bench", "meta-oss-agents", "mcp-registry"],
    market: ["ai-layoffs"],
    builders: ["meta-oss-agents", "mcp-registry"],
    leaders: ["agent-runtime", "claude-code-team"],
  },

  // ── Agent Watch ─────────────────────────────────────────────────────────
  agentWatch: [
    {
      name: "OpenAI Agent Runtime",
      track: "Agent runtime systems",
      buildable: "Yes — deploy agents as managed services today.",
      production: "Early. Durable execution is solid; governance is shallow.",
      moat: "Default tool-authorization + model lock-in.",
      demo: "Show a long-running, budget-capped agent with per-step traces.",
      storyId: "agent-runtime",
    },
    {
      name: "MCP Registry + Security Profile",
      track: "MCP servers / tool calling",
      buildable: "Yes — publish and discover signed, scoped servers.",
      production: "Maturing. Discovery is here; trust model is early.",
      moat: "Discovery + trust for the agent-tool interface.",
      demo: "Wire an agent to a signed MCP server with least-privilege scopes.",
      storyId: "mcp-registry",
    },
    {
      name: "Claude Code (Teams)",
      track: "AI coding agents",
      buildable: "Yes — repo-level agents with policy + audit.",
      production: "Yes, for teams with review gates in place.",
      moat: "Workflow + governance surface, not raw completion.",
      demo: "Agent opens a PR with provenance; human approves via handoff.",
      storyId: "claude-code-team",
    },
    {
      name: "Open Agent Models (Meta)",
      track: "Open-source agents / tool use",
      buildable: "Yes — self-host a tool-calling model.",
      production: "Depends on your serving + eval maturity.",
      moat: "Data residency + cost, if you can operate it.",
      demo: "Run a fully in-house agent loop on private data.",
      storyId: "meta-oss-agents",
    },
  ],

  // ── Builder Radar ───────────────────────────────────────────────────────
  builderRadar: [
    {
      repo: "agent-runtime-oss",
      stars: "+3.4k this week",
      what: "Self-hostable durable runtime for long-running agents.",
      why: "Own your agent control loop without a managed lock-in.",
      compare: "Temporal, Inngest, OpenAI Agent Runtime",
    },
    {
      repo: "mcp-server-kit",
      stars: "+2.1k this week",
      what: "Scaffolding to author signed, scoped MCP servers fast.",
      why: "MCP authoring is becoming a core integration skill.",
      compare: "OpenAPI generators, gRPC tooling",
    },
    {
      repo: "agent-evals",
      stars: "+1.7k this week",
      what: "Task-based eval harness with contamination-controlled splits.",
      why: "Demo-driven dev is out; eval-gated shipping is in.",
      compare: "SWE-bench harness, internal eval scripts",
    },
    {
      repo: "tool-broker",
      stars: "+980 this week",
      what: "Least-privilege permission broker for agent tool calls.",
      why: "Scoped permissions are only as good as enforcement.",
      compare: "OAuth scopes, policy engines (OPA)",
    },
  ],

  // ── Benchmark Watch ─────────────────────────────────────────────────────
  benchmarkWatch: [
    {
      name: "SWE-bench (refreshed)",
      change: "New post-cutoff split; leaders re-separated.",
      verified: "Maintainer-run; independent replication pending.",
      saturated: "Was saturating — refresh restores signal.",
      takeaway: "Use as a regression signal; keep private held-out tasks.",
      storyId: "swe-bench",
    },
    {
      name: "Long-context tool use (Gemini)",
      change: "New SOTA claimed with a clear margin.",
      verified: "Single-vendor; not independently reproduced.",
      saturated: "Prone to saturation; easy to teach to.",
      takeaway: "Verify on your own long, tool-heavy tasks first.",
      storyId: "gemini-bench",
    },
    {
      name: "Agent reliability (long runs)",
      change: "Industry shift toward measuring multi-step success.",
      verified: "Methodology varies widely across vendors.",
      saturated: "Far from saturated — the real frontier.",
      takeaway: "This, not single-turn Q&A, predicts production pain.",
      storyId: "agent-runtime",
    },
  ],

  // ── AI Company Map ──────────────────────────────────────────────────────
  companyMap: {
    "Foundation models": ["OpenAI", "Anthropic", "Google DeepMind", "Meta", "Mistral"],
    "Coding agents": ["Claude Code", "Cursor", "Codex-style agents", "Windsurf"],
    "Agent infra": ["Agent runtimes", "Orchestration libs", "Tool brokers", "Durable execution"],
    "Search / answer engines": ["Perplexity", "AI overviews", "Enterprise RAG"],
    "Observability": ["Agent tracing", "Eval platforms", "LLM monitoring"],
    "Data platforms": ["Vector stores", "Feature/context stores", "Pipelines"],
    "Enterprise AI": ["Copilots", "Workflow automation", "Governance & audit"],
    "Consumer AI": ["Assistants", "Companion apps", "Creative tools"],
    "Hardware": ["GPUs / accelerators", "Inference appliances", "Edge agents"],
  },

  weeklyDeepDive: "deep-dive",

  // ── Timeline mode ───────────────────────────────────────────────────────
  timelines: {
    "AI Coding Agents": [
      { year: "2023", text: "Copilot-style inline autocomplete." },
      { year: "2024", text: "Chat-based coding assistants." },
      { year: "2025", text: "Repo-aware coding agents." },
      { year: "2026", text: "Team workflow agents + runtime governance." },
    ],
  },

  // ── Compare mode ────────────────────────────────────────────────────────
  compares: [
    {
      title: "Claude Code vs Cursor vs Codex-style agents",
      columns: ["Claude Code", "Cursor", "Codex-style"],
      rows: [
        { dim: "Primary surface", vals: ["Terminal + repo", "IDE", "API / CI"] },
        { dim: "Team / governance", vals: ["Policy + audit", "Team tiers", "Varies"] },
        { dim: "Best for", vals: ["Repo-level workflows", "In-editor flow", "Programmatic tasks"] },
      ],
    },
    {
      title: "LangGraph vs CrewAI vs AutoGen",
      columns: ["LangGraph", "CrewAI", "AutoGen"],
      rows: [
        { dim: "Model", vals: ["Graph / state machine", "Role-based crews", "Conversational agents"] },
        { dim: "Control", vals: ["Explicit, fine-grained", "Higher-level", "Message-driven"] },
        { dim: "Best for", vals: ["Deterministic flows", "Quick multi-agent", "Research / prototyping"] },
      ],
    },
    {
      title: "OpenAI vs Anthropic vs Gemini for tool use",
      columns: ["OpenAI", "Anthropic", "Gemini"],
      rows: [
        { dim: "Strength", vals: ["Runtime + ecosystem", "Agentic coding + safety", "Long context"] },
        { dim: "Watch-out", vals: ["Lock-in", "Throughput at scale", "Benchmark vs reality"] },
      ],
    },
  ],

  // ── Roles for the persona switcher ──────────────────────────────────────
  roles: ["Engineering Leader", "Founder", "Developer", "Researcher", "Investor", "Product Manager"],
  defaultRole: "Engineering Leader",

  nav: ["Today", "Models", "Agents", "Coding", "Research", "Infra", "Startups", "Benchmarks", "Tools", "Weekly Brief"],
};
