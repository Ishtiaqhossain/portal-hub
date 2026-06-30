# The AI Brief

> Know what changed in AI, why it matters, and what to do with it.

A newspaper-style daily briefing that turns the chaotic AI news stream into a
clean, opinionated front page for **builders, leaders, and researchers**. Not
"more AI news" — every story answers *what changed, why you should care, and
what to do next*, and carries a **Skeptical read** so the site feels smarter
than an aggregator.

This is a **zero-dependency static MVP**: hand-written HTML/CSS/JS, no build
step, no framework, no CDN. It ships with a curated **sample edition** so every
section is alive and demonstrable.

## Run

It's static. Any of these work:

```bash
# 1. Just open it
open ai-brief/index.html              # macOS  (xdg-open on Linux)

# 2. Or serve it (recommended; stdlib only, matches the repo ethos)
cd ai-brief && python3 -m http.server 8000
#  -> http://localhost:8000
```

No `npm`, no `pip`, no tooling. Content is attached to `window.EDITION` in
`data.js` (not `fetch`-ed), so it also works when opened directly via `file://`.

## What's here

| File | Purpose |
|------|---------|
| `index.html`  | Front page shell (Today's Edition). |
| `article.html`| Article template; renders a story by `?id=`. |
| `data.js`     | All content: `window.EDITION` (stories, 5 Things, Agent Watch, Benchmark Watch, Company Map, deep dive, timelines, compares). |
| `app.js`      | Rendering + interactivity (vanilla JS). |
| `styles.css`  | The look: serif headlines, off-white canvas, electric-blue accent. |

## Sections (all driven from `data.js`)

- **Today's Edition** — lead story, Top Stories, Market/Industry, For Builders, For Leaders.
- **The 5 Things That Matter** — the daily executive summary.
- **Agent Watch** — coding agents, MCP servers, runtimes, evals — each with
  *Can I build with this? Production-ready? What's the moat? Interview demo?*
- **Builder Radar** — trending repos with stars, what/why, and comparable tools.
- **Benchmark Watch** — every score change gets a "so what": verified? saturated? practical takeaway?
- **AI Company Map** — the landscape by category.
- **Weekly Deep Dive** — the Sunday long read.
- **Timeline mode** and **Compare mode** for major topics, tools, and models.

## Signature features

- **Signal score** on every story — *Signal / Novelty / Practical value / Hype risk* (hype is color-inverted: high hype = caution).
- **Skeptical read** section — what could be overhyped or unclear.
- **"Why this matters to you"** persona switcher — pick a role
  (Engineering Leader, Founder, Developer, Researcher, Investor, Product Manager)
  and story implications rewrite for it. The choice persists across pages
  (localStorage); default persona is **Engineering Leader**.
- **Email signup** — captures locally (`localStorage`); wire to a real list in production.

## Article structure

Each brief follows the same skimmable spine:

`Headline → one-sentence takeaway → Signal score → Who should care →
What happened → What changed → Why it matters → Skeptical read →
Why this matters to you (persona) → Sources → Related.`

## Editing content

Everything is data. To change the edition, edit `data.js`:

- Add a story to `stories` (give it a unique `id`, a `signal` block, and a
  `personas` entry per role), then reference its `id` from `lead`,
  `fiveThings`, `sections`, `agentWatch`, `benchmarkWatch`, etc.
- No rebuild — reload the page.

After editing `app.js`, lint it (Node is a dev convenience, **not** a runtime dep):

```bash
node --check ai-brief/app.js
```

## Make it live (next steps toward the full product)

The static MVP is intentionally the floor. To turn it into a real daily brief:

1. **Digest generator** — pull sources (company blogs, arXiv, Hugging Face
   papers, GitHub trending, Hacker News, r/LocalLLaMA, newsletters, benchmark
   leaderboards), summarize with an LLM into the `EDITION` schema, write
   `data.js` (or a JSON the page fetches) once a day.
2. **Real signup** — POST the email to a list provider instead of `localStorage`.
3. **Publishing** — keep the JSON/MDX-as-content model; add an admin or a
   markdown pipeline.
4. **Search** — Postgres full-text or Meilisearch over the story bank.

The schema in `data.js` is the contract — fill it from whatever pipeline you like.
