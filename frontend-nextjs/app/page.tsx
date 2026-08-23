"use client";

/* ===========================================================================
   SoldierIQ — landing page.  DIRECTION CONTRACT (seed 30009de6 · persuade)
   ---------------------------------------------------------------------------
   THESIS: SoldierIQ answers as a finished all-source intelligence estimate —
     assessed answer, confidence lexicon, footnoted A–F/1–6 source grading.
     It refuses BOTH the dark-HUD "tactical dashboard" and the neutral
     enterprise-SaaS hero.
   OWN-WORLD: A dark analytic operations surface (graphite-green ground, olive
     drab + signal red, ledger ruling) on which one warm "estimate sheet" is
     worked. Saira Condensed command display · Public Sans (US-gov) body ·
     Overpass Mono for source data, citations, and reliability grades.
   STORY: A visitor sees their corpus become cited, graded answers and
     intelligence products; believes provenance is real because every claim is
     traced and every source graded; requests access.
   FIRST VIEWPORT: Left — monumental condensed headline + lead + primary
     action + live archive instruments. Right — a live INTELLIGENCE ESTIMATE
     sheet: query, cited assessment, source-reliability ledger, and the
     signature reliability-scrub that re-grades the answer in real time.
   FORM: The Intelligence Estimate; candidate #1 of my grounded list (my pick,
     chosen by the user over the assigned roll); seed key 30009de6.
   FINISH: unreviewed and undocumented is unfinished; this build ends with the
     finish review, the verdict, and DESIGN.md.
   =========================================================================== */

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/stores/authStore";

/* ---- Source-reliability model (NATO Admiralty code A–F / 1–6) ---------- */
const REL = ["F", "E", "D", "C", "B", "A"]; // index 0 (worst) → 5 (best)

type Source = {
  n: string;
  title: string;
  kind: string;
  rel: number; // 0..5 → REL letter
  cred: number; // 1..6
};

const SOURCES: Source[] = [
  { n: "1", title: "FM 3-21.8 — Infantry Rifle Platoon", kind: "Doctrine", rel: 5, cred: 2 },
  { n: "2", title: "Comms SOP 042", kind: "Unit SOP", rel: 4, cred: 2 },
  { n: "3", title: "After-action — Patrol 7, 04 APR", kind: "AAR", rel: 3, cred: 3 },
  { n: "4", title: "Radio transcript — Patrol 7 net", kind: "Transcript", rel: 2, cred: 4 },
  { n: "5", title: "Field video — keyframe 0447", kind: "Imagery", rel: 3, cred: 4 },
  { n: "6", title: "Unverified patrol log note", kind: "Raw", rel: 0, cred: 6 },
];

const gradeOf = (s: Source) => `${REL[s.rel]}${s.cred}`;
const gradeClass = (rel: number) =>
  rel >= 4 ? "iq-grade-hi" : rel >= 2 ? "iq-grade-md" : "iq-grade-lo";

type Clause = { text: string; cites: string[] };

// The assessed answer, sentence by sentence, each tied to its sources.
const ASSESSMENT: Clause[] = [
  { text: "SOP 042 diverges from FM 3-21.8 on callsign rotation.", cites: ["1", "2"] },
  { text: "The 04 APR after-action ties Patrol 7's net confusion to that gap.", cites: ["3"] },
  { text: "Radio and video place the breakdown at the 0447 crossing.", cites: ["4", "5"] },
  { text: "An unverified note suggests a mis-brief — uncorroborated.", cites: ["6"] },
];

/* ---- Small animated instrument counter -------------------------------- */
function Counter({ to, className }: { to: number; className?: string }) {
  const [val, setVal] = useState(0);
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let cancelled = false;
    let io: IntersectionObserver | null = null;
    const run = () => {
      if (reduce) {
        setVal(to);
        return;
      }
      const start = performance.now();
      const dur = 1100;
      const tick = (now: number) => {
        if (cancelled) return;
        const p = Math.min(1, (now - start) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        setVal(Math.round(to * eased));
        if (p < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };
    const rect = el.getBoundingClientRect();
    const inView = rect.top < window.innerHeight && rect.bottom > 0;
    if (inView) {
      run();
    } else {
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) {
              run();
              io?.disconnect();
            }
          });
        },
        { threshold: 0.4 }
      );
      io.observe(el);
    }
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      io?.disconnect();
    };
  }, [to]);
  return (
    <span ref={ref} className={className}>
      {val.toLocaleString()}
    </span>
  );
}

export default function Home() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const [zulu, setZulu] = useState("------Z");

  // Signature interaction: minimum source reliability the reader will accept.
  const [minBar, setMinBar] = useState(0); // 0 = F (all) … 5 = A (strict)

  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const p = (n: number) => String(n).padStart(2, "0");
      setZulu(`${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}Z`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (user) router.push("/dashboard");
  }, [user, router]);

  // Scroll reveal — consistent, restrained; the scrub is the authored moment.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const els = Array.from(root.querySelectorAll<HTMLElement>(".iq-reveal"));
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      els.forEach((el) => el.classList.add("iq-in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("iq-in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.16, rootMargin: "0px 0px -8% 0px" }
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  // DTG (date-time group): 181234ZAPR26
  const now = new Date();
  const dtg = `${String(now.getUTCDate()).padStart(2, "0")}${String(
    now.getUTCHours()
  ).padStart(2, "0")}${String(now.getUTCMinutes()).padStart(2, "0")}Z${now
    .toLocaleString("en-US", { month: "short", timeZone: "UTC" })
    .toUpperCase()}${String(now.getUTCFullYear()).slice(2)}`;

  // Derived state from the reliability scrub. The scrub filters the source
  // ledger and recomputes the readouts; the assessment text stays intact.
  const model = useMemo(() => {
    const retained = SOURCES.filter((s) => s.rel >= minBar);
    const meanRel =
      retained.length === 0
        ? null
        : Math.round(retained.reduce((a, s) => a + s.rel, 0) / retained.length);
    const confidence =
      retained.length >= 5
        ? "SUBSTANTIATED"
        : retained.length >= 3
        ? "PARTIAL"
        : retained.length >= 1
        ? "THIN"
        : "INSUFFICIENT";
    return { retained, meanRel, confidence };
  }, [minBar]);

  return (
    <div ref={rootRef} className="iqx min-h-screen">
      {/* ── Classification strip ───────────────────────────────────────── */}
      <div className="iq-class">
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 h-7 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className="iq-dot iq-dot-sig" />
            UNCLASSIFIED&nbsp;&nbsp;//&nbsp;&nbsp;Field-Ready Preview
          </span>
          <span className="hidden sm:inline">
            SIQ-01 · Build 0.9.4 · DTG&nbsp;<span className="text-[var(--iq-ink)]">{dtg}</span>
          </span>
          <span className="sm:hidden iq-tnum">{zulu}</span>
        </div>
      </div>

      {/* ── Masthead ───────────────────────────────────────────────────── */}
      <header className="border-b border-[var(--iq-rule-2)] bg-[var(--iq-bg)]/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3">
            <Reticle />
            <span className="iq-cmd text-[19px] text-[var(--iq-ink-strong)]">SoldierIQ</span>
            <span className="iq-label hidden sm:inline pl-1">Operational Knowledge System</span>
          </Link>
          <nav className="flex items-center gap-6">
            <Link href="/auth/login" className="iq-label iq-under !text-[var(--iq-ink)]">
              Sign in
            </Link>
            <Link href="/auth/signup" className="iq-btn">
              Request access
              <Arrow />
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Status strip ───────────────────────────────────────────────── */}
      <div className="border-b border-[var(--iq-rule)]">
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 h-9 flex items-center justify-between">
          <div className="flex items-center gap-5 iq-label">
            <span className="flex items-center gap-2">
              <span className="iq-dot iq-dot-ok iq-live" /> Status&nbsp;<span className="text-[var(--iq-ink)]">Ready</span>
            </span>
            <span className="hidden sm:inline w-px h-3 bg-[var(--iq-rule-2)]" />
            <span className="hidden sm:inline">
              Archive&nbsp;<span className="text-[var(--iq-ink)] iq-tnum">1,247</span>&nbsp;rec
            </span>
            <span className="hidden md:inline w-px h-3 bg-[var(--iq-rule-2)]" />
            <span className="hidden md:inline">
              Graph&nbsp;<span className="text-[var(--iq-ink)]">2-layer</span>
            </span>
            <span className="hidden lg:inline w-px h-3 bg-[var(--iq-rule-2)]" />
            <span className="hidden lg:inline">Edge&nbsp;+&nbsp;Cloud</span>
          </div>
          <div className="iq-label flex items-center gap-2">
            <span className="hidden sm:inline">UTC</span>
            <span className="text-[var(--iq-ink)] iq-tnum">{zulu}</span>
          </div>
        </div>
      </div>

      {/* ── HERO ───────────────────────────────────────────────────────── */}
      <section className="border-b border-[var(--iq-rule-2)] relative overflow-hidden">
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 pt-14 lg:pt-20 pb-16 lg:pb-24">
          <div className="grid grid-cols-12 gap-8 lg:gap-12 items-start">
            {/* Left — thesis */}
            <div className="col-span-12 lg:col-span-6">
              <h1 className="iq-display text-[15vw] sm:text-[86px] lg:text-[104px] text-[var(--iq-ink-strong)] iq-reveal iq-in">
                Every answer
                <br />
                cites the source
                <br />
                that <span className="text-[var(--iq-od)]">proves it</span>.
              </h1>

              <p className="mt-8 max-w-[42ch] text-[17px] leading-[1.6] text-[var(--iq-ink-muted)] iq-reveal iq-in iq-d1">
                Your corpus, answered as a cited intelligence estimate — every
                claim graded and traced to its source.
              </p>

              <div className="mt-9 flex flex-wrap items-center gap-3 iq-reveal iq-in iq-d2">
                <Link href="/auth/signup" className="iq-btn">
                  Request access
                  <Arrow />
                </Link>
                <Link href="/auth/login" className="iq-btn-ghost">
                  Sign in
                </Link>
              </div>

              {/* Live archive instruments */}
              <div className="mt-12 pt-6 border-t border-[var(--iq-rule)] grid grid-cols-3 gap-4 max-w-[440px] iq-reveal iq-in iq-d3">
                <div>
                  <div className="iq-mono text-[30px] leading-none text-[var(--iq-ink-strong)] iq-tnum">
                    <Counter to={1247} />
                  </div>
                  <div className="iq-label mt-2">Records indexed</div>
                </div>
                <div>
                  <div className="iq-mono text-[30px] leading-none text-[var(--iq-ink-strong)] iq-tnum">
                    <Counter to={112} />
                  </div>
                  <div className="iq-label mt-2">Sources graded</div>
                </div>
                <div>
                  <div className="iq-mono text-[30px] leading-none text-[var(--iq-ink-strong)] iq-tnum">
                    100<span className="text-[var(--iq-od)]">%</span>
                  </div>
                  <div className="iq-label mt-2">Claims cited</div>
                </div>
              </div>
            </div>

            {/* Right — the live estimate sheet */}
            <div className="col-span-12 lg:col-span-6 iq-reveal iq-in iq-d2">
              <div className="flex items-center justify-between mb-3">
                <span className="iq-label iq-label-od flex items-center gap-2">
                  <span className="iq-dot iq-dot-sig iq-live" /> Fig. I — Intelligence estimate, live
                </span>
                <span className="iq-label">Sanitised for preview</span>
              </div>
              <EstimateSheet
                dtg={dtg}
                minBar={minBar}
                setMinBar={setMinBar}
                model={model}
              />
            </div>
          </div>
        </div>
      </section>

      {/* ── FIG. II — Intelligence products (capabilities) ─────────────── */}
      <section className="border-b border-[var(--iq-rule-2)]">
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 py-16 lg:py-24">
          <div className="grid grid-cols-12 gap-8 lg:gap-12 mb-12 lg:mb-16">
            <div className="col-span-12 lg:col-span-6">
              <h2 className="iq-display text-[44px] sm:text-[60px] lg:text-[72px] text-[var(--iq-ink-strong)] iq-reveal iq-in iq-d1">
                Four ways to work
                <br />
                <span className="text-[var(--iq-ink-muted)]">your own corpus.</span>
              </h2>
            </div>
            <div className="col-span-12 lg:col-span-5 lg:col-start-8 self-end iq-reveal iq-in iq-d2">
              <p className="text-[16px] leading-[1.7] text-[var(--iq-ink-muted)]">
                Each answers one operational question — fast, cited, reproducible.
              </p>
            </div>
          </div>

          <div className="border-t border-[var(--iq-rule-2)]">
            {MODULES.map((m, i) => (
              <div
                key={m.code}
                className="iq-reveal iq-in grid grid-cols-12 gap-4 lg:gap-8 py-8 lg:py-10 border-b border-[var(--iq-rule)] group"
                style={{ animationDelay: `${i * 70}ms` }}
              >
                <div className="col-span-12 lg:col-span-3">
                  <h3 className="iq-cmd text-[30px] text-[var(--iq-ink-strong)] leading-none">
                    {m.name}
                  </h3>
                  <div className="iq-label mt-2">{m.tag}</div>
                </div>
                <div className="col-span-12 lg:col-span-6">
                  <p className="text-[15.5px] leading-[1.68] text-[var(--iq-ink-muted)] max-w-[52ch]">
                    {m.body}
                  </p>
                </div>
                <div className="col-span-12 lg:col-span-3 flex flex-wrap gap-1.5 lg:justify-end content-start">
                  {m.bullets.map((b) => (
                    <span
                      key={b}
                      className="iq-mono text-[11px] text-[var(--iq-ink)] px-2 py-1 border border-[var(--iq-rule-2)] bg-[var(--iq-bg-2)]"
                    >
                      {b}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── FIG. III — Two-layer provenance ────────────────────────────── */}
      <section className="border-b border-[var(--iq-rule-2)]">
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 py-16 lg:py-24">
          <div className="grid grid-cols-12 gap-8 lg:gap-14 items-center">
            <div className="col-span-12 lg:col-span-5">
              <h2 className="iq-display text-[40px] sm:text-[52px] lg:text-[60px] text-[var(--iq-ink-strong)] iq-reveal iq-in iq-d1">
                A reliable layer
                <br />
                beneath the
                <br />
                <span className="text-[var(--iq-od)]">meaning.</span>
              </h2>
              <p className="mt-7 text-[16px] leading-[1.7] text-[var(--iq-ink-muted)] max-w-[40ch] iq-reveal iq-in iq-d2">
                Meaning above, exact document → chunk lineage beneath. Even when
                extraction is imperfect, every answer traces to the passage that
                produced it.
              </p>
            </div>
            <div className="col-span-12 lg:col-span-6 lg:col-start-7 iq-reveal iq-in iq-d2">
              <TwoLayerDiagram />
            </div>
          </div>
        </div>
      </section>

      {/* ── DEPLOY CTA ─────────────────────────────────────────────────── */}
      <section className="border-b border-[var(--iq-rule-2)]">
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 py-20 lg:py-28">
          <div className="grid grid-cols-12 gap-8 items-end">
            <div className="col-span-12 lg:col-span-8">
              <h2 className="iq-display text-[46px] sm:text-[64px] lg:text-[82px] text-[var(--iq-ink-strong)] iq-reveal iq-in iq-d1">
                Bring your archive.
                <br />
                <span className="text-[var(--iq-od)]">Begin operations.</span>
              </h2>
              <p className="mt-6 max-w-[40ch] text-[16px] leading-[1.7] text-[var(--iq-ink-muted)] iq-reveal iq-in iq-d2">
                The same product at the edge and in the cloud. Connectivity is an
                enhancement, not a requirement.
              </p>
            </div>
            <div className="col-span-12 lg:col-span-4 flex flex-wrap lg:justify-end gap-3 iq-reveal iq-in iq-d2">
              <Link href="/auth/signup" className="iq-btn">
                Request access
                <Arrow />
              </Link>
              <Link href="/auth/login" className="iq-btn-ghost">
                Sign in
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer>
        <div className="mx-auto max-w-[1320px] px-6 lg:px-10 py-12">
          <div className="grid grid-cols-12 gap-8">
            <div className="col-span-12 lg:col-span-4">
              <div className="flex items-center gap-3 mb-4">
                <Reticle />
                <span className="iq-cmd text-[17px] text-[var(--iq-ink-strong)]">SoldierIQ</span>
              </div>
              <p className="text-[13.5px] leading-[1.7] text-[var(--iq-ink-muted)] max-w-[36ch]">
                Operational knowledge system for field-intelligence teams.
              </p>
            </div>

            <div className="col-span-6 lg:col-span-2">
              <div className="iq-label mb-4">Access</div>
              <ul className="space-y-2.5 text-[14px]">
                <li><Link href="/auth/login" className="iq-under">Sign in</Link></li>
                <li><Link href="/auth/signup" className="iq-under">Request access</Link></li>
                <li><Link href="/request-access" className="iq-under">System-owner access</Link></li>
              </ul>
            </div>

            <div className="col-span-6 lg:col-span-2">
              <div className="iq-label mb-4">System</div>
              <ul className="space-y-2.5 text-[13px] text-[var(--iq-ink-muted)] iq-mono">
                <li>SIQ-01 · v0.9.4</li>
                <li>Build d82af1c</li>
                <li className="flex items-center gap-2"><span className="iq-dot iq-dot-ok" /> all systems</li>
              </ul>
            </div>

            <div className="col-span-12 lg:col-span-4">
              <div className="iq-label mb-4">Handling</div>
              <p className="text-[12.5px] leading-[1.66] text-[var(--iq-ink-muted)] max-w-[34ch]">
                No classified information in preview. Demonstration data is
                synthetic.
              </p>
            </div>
          </div>

          <div className="iq-hair mt-10 mb-4" />
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
            <span className="iq-label">© MMXXVI · SoldierIQ · All rights reserved</span>
            <span className="iq-label">
              UNCLASSIFIED <span className="text-[var(--iq-sig)]">//</span> Field-Ready Preview
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* =========================================================================
   The estimate sheet — the warm document worked on the ops surface.
   ========================================================================= */
function EstimateSheet({
  dtg,
  minBar,
  setMinBar,
  model,
}: {
  dtg: string;
  minBar: number;
  setMinBar: (n: number) => void;
  model: {
    retained: Source[];
    meanRel: number | null;
    confidence: string;
  };
}) {
  return (
    <div className="iq-paper iq-reg p-5 lg:p-6">
      {/* header */}
      <div className="flex items-baseline justify-between pb-3 mb-4 border-b border-[var(--iq-paper-rule)]">
        <div>
          <div className="iq-cmd text-[17px] text-[var(--iq-paper-ink)] leading-none">
            Intelligence Estimate
          </div>
          <div className="iq-mono text-[10.5px] text-[var(--iq-paper-mut)] mt-1 uppercase tracking-[0.14em]">
            Ref EST 038-A · Op Nightwatch
          </div>
        </div>
        <div className="iq-mono text-[10.5px] text-[var(--iq-paper-mut)] text-right leading-relaxed">
          DTG {dtg}
          <br />
          {model.retained.length}/{SOURCES.length} sources in scope
        </div>
      </div>

      {/* requirement */}
      <div className="mb-4">
        <div className="iq-mono text-[9.5px] uppercase tracking-[0.16em] text-[var(--iq-paper-sig)] mb-1.5">
          Requirement
        </div>
        <p className="iq-mono text-[13px] leading-[1.45] text-[var(--iq-paper-ink)]">
          Summarise comms protocol across SOPs 040–044 and flag contradictions.
        </p>
      </div>

      {/* assessment */}
      <div className="mb-5">
        <div className="iq-mono text-[9.5px] uppercase tracking-[0.16em] text-[var(--iq-paper-sig)] mb-1.5">
          Assessment
        </div>
        <p className="text-[14.5px] leading-[1.72] text-[var(--iq-paper-ink)]">
          {ASSESSMENT.map((c, i) => (
            <span key={i}>
              {c.text.replace(/\.$/, "")}
              {c.cites.map((n) => {
                const s = SOURCES.find((x) => x.n === n)!;
                return (
                  <sup
                    key={n}
                    className="iq-cite"
                    title={`§${n} ${s.title} · ${gradeOf(s)}`}
                  >
                    [{n}]
                  </sup>
                );
              })}
              {". "}
            </span>
          ))}
        </p>
      </div>

      {/* the reliability scrub */}
      <div className="mb-5 pt-4 border-t border-[var(--iq-paper-rule)]">
        <div className="flex items-baseline justify-between mb-2">
          <label
            htmlFor="iq-rel"
            className="iq-mono text-[9.5px] uppercase tracking-[0.16em] text-[var(--iq-paper-mut)]"
          >
            Minimum source reliability
          </label>
          <span className="iq-mono text-[20px] leading-none font-bold text-[var(--iq-paper-sig)]">
            {REL[minBar]}
          </span>
        </div>
        <input
          id="iq-rel"
          className="iq-range"
          type="range"
          min={0}
          max={5}
          step={1}
          value={minBar}
          onChange={(e) => setMinBar(Number(e.target.value))}
          aria-valuetext={`Minimum reliability ${REL[minBar]}`}
        />
        <div className="flex justify-between iq-mono text-[9.5px] text-[var(--iq-paper-mut)] mt-0.5">
          <span>F · accept all</span>
          <span>A · reliable only</span>
        </div>

        {/* readouts */}
        <div className="grid grid-cols-2 gap-2 mt-4">
          <Readout label="Sources retained" value={`${model.retained.length}/${SOURCES.length}`} />
          <Readout label="Mean grade" value={model.meanRel === null ? "—" : REL[model.meanRel]} />
        </div>
        <div className="mt-3 flex items-center justify-between">
          <span className="iq-mono text-[9.5px] uppercase tracking-[0.16em] text-[var(--iq-paper-mut)]">
            Assessed confidence
          </span>
          <span
            className="iq-mono text-[12px] font-bold tracking-[0.08em]"
            style={{
              color:
                model.retained.length >= 5
                  ? "#4E6B34"
                  : model.retained.length >= 3
                  ? "#8A6D1E"
                  : "var(--iq-paper-sig)",
            }}
          >
            {model.confidence}
          </span>
        </div>
      </div>

      {/* sources ledger */}
      <div>
        <div className="iq-mono text-[9.5px] uppercase tracking-[0.16em] text-[var(--iq-paper-mut)] mb-2">
          Sources · reliability A–F / credibility 1–6
        </div>
        <ul>
          {SOURCES.map((s) => {
            const off = s.rel < minBar;
            return (
              <li
                key={s.n}
                className={`iq-src-row flex items-center gap-3 py-1.5 border-b border-[var(--iq-paper-rule)]/60 ${
                  off ? "iq-src-off" : ""
                }`}
              >
                <span className="iq-mono text-[11px] font-bold text-[var(--iq-paper-mut)] w-4">
                  {s.n}
                </span>
                <span className="flex-1 text-[13px] text-[var(--iq-paper-ink)] truncate">
                  {s.title}
                </span>
                <span className="iq-mono text-[9.5px] uppercase tracking-[0.12em] text-[var(--iq-paper-mut)] hidden sm:inline">
                  {s.kind}
                </span>
                <span className={`iq-grade ${gradeClass(s.rel)}`}>{gradeOf(s)}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-[var(--iq-paper-rule)] px-2.5 py-2">
      <div className="iq-mono text-[16px] font-bold leading-none text-[var(--iq-paper-ink)] iq-tnum">
        {value}
      </div>
      <div className="iq-mono text-[8.5px] uppercase tracking-[0.14em] text-[var(--iq-paper-mut)] mt-1.5">
        {label}
      </div>
    </div>
  );
}

/* =========================================================================
   Two-layer provenance diagram — geometry, not illustration.
   ========================================================================= */
function TwoLayerDiagram() {
  return (
    <div className="iq-panel iq-reg p-6 lg:p-8">
      <div className="flex items-center justify-between mb-6">
        <span className="iq-label iq-label-od">Fig. II — Registered graph layers</span>
        <span className="iq-label">Schematic</span>
      </div>
      <svg viewBox="0 0 420 300" className="w-full h-auto" role="img" aria-label="Two registered graph layers: a meaning layer of entities and relationships above a lexical layer of documents and chunks, tied by provenance links.">
        <defs>
          <marker id="iqdot" markerWidth="6" markerHeight="6" refX="3" refY="3">
            <circle cx="3" cy="3" r="2" fill="#B2AA7D" />
          </marker>
        </defs>

        {/* Meaning layer (top plate) */}
        <g transform="translate(0,6)">
          <rect x="20" y="14" width="380" height="104" fill="rgba(178,170,125,0.05)" stroke="#2C3430" />
          <text x="30" y="34" fill="#B2AA7D" fontFamily="Overpass Mono, monospace" fontSize="10" letterSpacing="1.4">MEANING LAYER — ENTITIES · DOCTRINE · RELATIONS</text>
          {/* nodes + edges */}
          <line x1="90" y1="72" x2="200" y2="58" stroke="#3a423e" markerEnd="url(#iqdot)" markerStart="url(#iqdot)" />
          <line x1="200" y1="58" x2="320" y2="80" stroke="#3a423e" markerEnd="url(#iqdot)" markerStart="url(#iqdot)" />
          <line x1="200" y1="58" x2="150" y2="96" stroke="#3a423e" markerEnd="url(#iqdot)" markerStart="url(#iqdot)" />
          <line x1="320" y1="80" x2="270" y2="100" stroke="#3a423e" markerEnd="url(#iqdot)" markerStart="url(#iqdot)" />
          {[
            [90, 72, "PLT"],
            [200, 58, "SOP 042"],
            [320, 80, "NET"],
            [150, 96, "FM 3-21"],
            [270, 100, "AAR"],
          ].map(([x, y, t], i) => (
            <g key={i}>
              <rect x={(x as number) - 26} y={(y as number) - 9} width="52" height="18" fill="#161D1B" stroke="#B2AA7D" />
              <text x={x as number} y={(y as number) + 3} fill="#E7E6DC" fontFamily="Overpass Mono, monospace" fontSize="8.5" textAnchor="middle">{t as string}</text>
            </g>
          ))}
        </g>

        {/* registration ties */}
        {[110, 190, 270].map((x, i) => (
          <line key={i} x1={x} y1="124" x2={x} y2="176" stroke="#CC4B39" strokeDasharray="3 3" opacity="0.7" />
        ))}

        {/* Lexical layer (bottom plate) */}
        <g transform="translate(0,0)">
          <rect x="20" y="182" width="380" height="104" fill="rgba(231,230,220,0.02)" stroke="#2C3430" />
          <text x="30" y="202" fill="#99A08F" fontFamily="Overpass Mono, monospace" fontSize="10" letterSpacing="1.4">LEXICAL LAYER — DOCUMENT → CHUNK LINEAGE</text>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <g key={i} transform={`translate(${44 + i * 60}, 218)`}>
              <rect width="44" height="52" fill="#101514" stroke="#2C3430" />
              {[0, 1, 2, 3].map((r) => (
                <line key={r} x1="7" y1={12 + r * 9} x2="37" y2={12 + r * 9} stroke={r === 1 ? "#CC4B39" : "#3a423e"} strokeWidth={r === 1 ? 1.6 : 1} />
              ))}
            </g>
          ))}
        </g>
      </svg>
      <p className="text-[13px] leading-[1.6] text-[var(--iq-ink-muted)] mt-5 pt-5 border-t border-[var(--iq-rule)]">
        Red ties are provenance. Pull an entity; its exact chunk comes with it.
      </p>
    </div>
  );
}

/* ---- Marks (drawn, one stroke weight) --------------------------------- */
function Reticle() {
  return (
    <span className="inline-flex items-center justify-center w-8 h-8 border border-[var(--iq-od)] relative">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <circle cx="8" cy="8" r="5" stroke="var(--iq-od)" strokeWidth="1" />
        <path d="M8 0v4M8 12v4M0 8h4M12 8h4" stroke="var(--iq-od)" strokeWidth="1" />
      </svg>
    </span>
  );
}

function Arrow() {
  return (
    <svg width="13" height="13" viewBox="0 0 12 12" fill="none" aria-hidden>
      <path d="M1 6h10M7 2l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" />
    </svg>
  );
}

/* ---- Capability content ----------------------------------------------- */
const MODULES = [
  {
    code: "01",
    name: "Query",
    tag: "Interrogation",
    body: "Ask the archive in plain language. Every answer traces to the source line.",
    bullets: ["Grounded answers", "Inline citations"],
  },
  {
    code: "02",
    name: "Map",
    tag: "Visualisation",
    body: "Entity and doctrine graphs on demand — a stack of SOPs as one readable map.",
    bullets: ["Concept graphs", "Exportable"],
  },
  {
    code: "03",
    name: "Synthesise",
    tag: "Product generation",
    body: "Reports, flashcards, and audio overviews built from your corpus.",
    bullets: ["Reports", "Flashcards", "Audio + voice"],
  },
  {
    code: "04",
    name: "Integrate",
    tag: "Field interop",
    body: "TAK routes, transcribed radio and video, per-file access control.",
    bullets: ["TAK-ready", "Per-file RBAC"],
  },
];
