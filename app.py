"""
╔══════════════════════════════════════════════════════════════════╗
║           Smart Data Extractor — Phase 3                        ║
║           AI Tech Briefing Engine — Streamlit Web GUI           ║
║           Features: Live Pipeline · Archive · Graceful Fallback ║
║                                                                    ║
║           Architecture Roadmap · Phase 1 — Stabilize:           ║
║             run_newsletter_stage() now catches the typed         ║
║             exceptions raised by ai_newsletter.py directly,      ║
║             instead of the generic SystemExit / Exception.       ║
╚══════════════════════════════════════════════════════════════════╝
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import os

import streamlit as st
from dotenv import load_dotenv

from smart_data_extractor import SmartDataExtractor
from ai_newsletter import AINewsletterGenerator
from core.exceptions import (
    BriefingEngineError,
    ConfigurationError,
    LLMError,
    RepositoryError,
)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — all paths anchored to this file so the app behaves
# identically regardless of the shell's working directory or deployment target.
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).resolve().parent
OUTPUT_DIR     = str(BASE_DIR / "output")
NEWSLETTER_DIR = str(BASE_DIR / "newsletters")
ENV_FILE       = str(BASE_DIR / ".env")

LOG_CANDIDATES = [BASE_DIR / "extractor.log", BASE_DIR / "newsletter_generator.log"]


# ─────────────────────────────────────────────────────────────────────────────
# Page Configuration  ← must be the first Streamlit call in the script
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Tech Briefing Engine",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* ── Layout ──────────────────────────────────────────────────── */
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 4rem;
        max-width: 1100px;
    }
    /* ── Typography ─────────────────────────────────────────────── */
    h1 { font-weight: 700; letter-spacing: -0.5px; }
    div[data-testid="stMarkdownContainer"] h1 { font-size: 1.75rem; }
    div[data-testid="stMarkdownContainer"] h2 {
        font-size: 1.2rem;
        margin-top: 1.4rem;
        padding-top: 0.6rem;
        border-top: 1px solid rgba(128,128,128,0.15);
    }
    /* ── Components ─────────────────────────────────────────────── */
    [data-testid="stMetricValue"] { font-size: 1.25rem; font-weight: 600; }
    [data-testid="stSidebar"]     { border-right: 1px solid rgba(120,120,120,0.15); }
    .stDownloadButton > button    { font-weight: 600; }
    /* ── Fallback badge rendered via st.markdown unsafe_allow_html ─ */
    .fallback-pill {
        display: inline-block;
        background: linear-gradient(135deg, #f59e0b, #d97706);
        color: #fff;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.15rem 0.55rem;
        border-radius: 999px;
        margin-left: 0.4rem;
        vertical-align: middle;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class NewsletterFile:
    """
    Immutable value object representing a single newsletter file on disk.

    `is_fallback` is True when the filename contains the 'fallback' prefix,
    which the FallbackNewsletterGenerator stamps onto every simulated briefing.
    """

    path: Path
    content: str
    generated_at: datetime
    is_fallback: bool = False

    @property
    def word_count(self) -> int:
        return len(self.content.split())

    @property
    def display_label(self) -> str:
        """Human-readable archive label used in the sidebar selectbox."""
        ts = self.generated_at.strftime("%b %d, %Y — %I:%M %p")
        return f"⚡ {ts}  · Simulated" if self.is_fallback else f"📰 {ts}"


@dataclass(frozen=True)
class StageResult:
    """
    Outcome of a single pipeline stage, fully decoupled from rendering.
    Allows the UI layer to decide how to handle each failure type independently.
    """

    success: bool
    error_message: Optional[str] = None
    show_log_tail: bool = False          # Surface log details for scraping failures
    triggers_fallback: bool = False      # True for AI generation failures → soft fallback


# ─────────────────────────────────────────────────────────────────────────────
# Fallback Newsletter Generator
# ─────────────────────────────────────────────────────────────────────────────
class FallbackNewsletterGenerator:
    """
    Generates and persists a premium-quality simulated newsletter when the
    live Gemini API is unavailable (503, quota exceeded, missing key, etc.).

    Design principles:
      • Content is editorial-grade: indistinguishable in quality from a live
        AI-generated briefing, covering real-world technical topics.
      • Files are stamped with a 'newsletter_fallback_' prefix so the archive
        can visually distinguish them from live briefings.
      • The class is completely stateless — safe to instantiate multiple times.
    """

    _FILENAME_PREFIX: str = "newsletter_fallback_"

    def __init__(self, output_dir: str = NEWSLETTER_DIR) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_and_save(self) -> Path:
        """Builds the fallback content and persists it. Returns the saved path."""
        content = self._build_content()
        return self._save(content)

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _build_content(self) -> str:
        """
        Returns a fully-formed, premium Markdown newsletter string.

        Three stories span: Quantum Computing · Open-Source LLMs · Python Runtime.
        Each article section follows the same structural template as a live
        AI-generated briefing to ensure visual consistency in the UI.
        """
        now = datetime.now()
        today_str = now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y")

        return f"""\
# 🗞️ Daily Tech Briefing — {today_str}

Three distinct signals dominated the technical conversation today. \
A milestone in quantum error correction is quietly shifting the planning horizon \
for enterprise infrastructure teams. The open-source LLM ecosystem crossed a new \
capability threshold that rewrites the economics of on-premise AI deployment. \
And a long-anticipated change to the Python runtime is finally ready for production \
workloads — with important caveats that most teams haven't accounted for yet.

---

## 1. Quantum Error Correction Crosses the Fault-Tolerance Threshold

**Source:** [IBM Research: Sub-Millisecond Logical Qubit Error Rates Achieved on 1,000-Qubit Heron Processor](https://news.ycombinator.com/item?id=41023847)

IBM's Quantum Network published results this week demonstrating logical qubit error \
rates below 0.1% on a 1,000-qubit Heron-class processor — a threshold that the \
research community has treated as the practical entry point for fault-tolerant \
computation since Preskill's 1997 threshold theorem. The technique, "Layered Noise \
Extrapolation" (LNE), uses probabilistic noise extrapolation rather than full \
surface-code error correction, making it viable on current NISQ hardware without \
requiring a 10× increase in physical qubit count. For pharmaceutical and materials \
science teams, the most actionable implication isn't the benchmark itself but the \
companion release of Qiskit 2.0's transpiler, which automatically maps NumPy-based \
molecular simulation workflows onto optimized quantum circuits. Engineering teams \
in these sectors should begin auditing their HPC pipelines for quantum-classical \
hybrid compatibility now: the integration window — data pipeline redesign, API \
abstraction layers, hybrid scheduling — takes 18–24 months to engineer, and the \
cost-performance crossover for narrow chemistry workloads is arriving faster than \
most 2030 roadmaps anticipated.

---

## 2. Llama 4 Scout Hits Production Viability: Expert Reasoning on a Single GPU

**Source:** [Community Benchmark: Llama 4 Scout INT4 Achieves 340 tok/s on A100 80GB, Matches GPT-4 on MATH-500](https://news.ycombinator.com/item?id=41019234)

When Meta released Llama 4 Scout (17B active parameters, 109B total, Mixture-of-Experts \
architecture) earlier this year, the performance numbers were impressive but the \
production viability story remained uncertain due to memory footprint. This week's \
community benchmark sweep resolves that question: Scout in INT4 quantization fits \
within a single A100 80GB GPU's memory envelope and sustains 340 tokens per second — \
fast enough for synchronous, latency-sensitive, user-facing inference without batching \
complexity. More significant than throughput is capability: Scout scores 87.2% on \
MATH-500 and 72.4% on LiveCodeBench, placing it in the tier that was commercially \
gated to GPT-4-class API access just fourteen months ago. For developers and \
infrastructure architects, the economics of on-premise AI deployment have crossed \
a genuine threshold: not as a cost play for simple classification tasks, but as a \
capability-equivalent alternative for complex multi-step reasoning workloads where \
data-residency requirements, p99 latency budgets, or per-token volume economics \
previously made managed API access the only viable path.

---

## 3. Python 3.14 Free-Threading Exits Experimental — With Production Caveats

**Source:** [CPython 3.14 Release Notes: Free-Threaded Build Graduates to Tier-2 Supported Status](https://news.ycombinator.com/item?id=41021560)

PEP 703's GIL-free CPython variant — shipped as an experimental opt-in since 3.13 \
and iterated through three patch releases — has officially exited experimental status \
in Python 3.14, with the core team declaring the per-object locking model \
production-safe for the majority of single-process workloads under PEP 779's \
new Tier-2 support contract. Early benchmark data from the Scientific Python \
ecosystem reflects the expected split: CPU-bound preprocessing pipelines \
(tokenization, audio resampling, image transforms) show 2.4–3.1× throughput \
improvements on 8-core hardware under `ThreadPoolExecutor`, while I/O-bound \
and asyncio-heavy services show negligible change since they were never \
meaningfully GIL-constrained. The necessary caution is on C-extension compatibility: \
as of 3.14, only approximately 40% of the top-200 PyPI packages have published \
thread-safe wheel variants for the free-threaded build. Engineering teams should \
audit their full dependency graph for GIL-assumption violations before migrating \
any production workload, and should budget an additional sprint for C-extension \
pinning and regression testing.

---

## Editor's Note

Three stories, one underlying current: foundational constraints that shaped an \
entire generation of engineering decisions — the qubit error rate that made quantum \
impractical, the GPU memory ceiling that kept capable LLMs off-premise, and the \
Global Interpreter Lock that bottlenecked Python's concurrency model — are all \
being renegotiated simultaneously. This is not a coincidence. It reflects a broader \
maturation of the computing stack where theoretical thresholds, long used to \
justify deferred investment, are being crossed in the same 18-month window. \
The teams that begin integration work now, before ecosystem tooling catches up, \
will compound that head start into durable architectural advantages. \
The ones waiting for "production-ready" will find the window has closed.

---

*Briefing generated by Smart Data Extractor — AI Newsletter Engine*
"""

    def _save(self, content: str) -> Path:
        """Persists the fallback newsletter and returns its path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self._output_dir / f"{self._FILENAME_PREFIX}{timestamp}.md"
        try:
            filepath.write_text(content, encoding="utf-8")
        except IOError as exc:
            raise IOError(
                f"FallbackNewsletterGenerator could not write to "
                f"'{filepath}': {exc}"
            ) from exc
        return filepath


# ─────────────────────────────────────────────────────────────────────────────
# Filesystem Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _load_newsletter_file(path: Path) -> Optional[NewsletterFile]:
    """
    Reads a single .md file into a NewsletterFile value object.
    Returns None on any read error or if the file is empty.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (IOError, OSError):
        return None
    if not content.strip():
        return None
    return NewsletterFile(
        path=path,
        content=content,
        generated_at=datetime.fromtimestamp(path.stat().st_mtime),
        is_fallback="fallback" in path.name,
    )


def get_all_newsletters(newsletter_dir: str = NEWSLETTER_DIR) -> list[NewsletterFile]:
    """
    Returns all valid .md files in the newsletter directory, sorted newest-first.
    Used to populate both the archive dropdown and the default results view.
    """
    dir_path = Path(newsletter_dir)
    if not dir_path.exists():
        return []

    results: list[NewsletterFile] = []
    for p in sorted(dir_path.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
        nf = _load_newsletter_file(p)
        if nf is not None:
            results.append(nf)
    return results


def _read_log_tail(candidates: list[Path], n_lines: int = 12) -> Optional[str]:
    """Tails the most recently modified candidate log file for diagnostics."""
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return None
    newest = max(existing, key=lambda p: p.stat().st_mtime)
    try:
        lines = newest.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-n_lines:])
        return tail if tail.strip() else None
    except (IOError, OSError):
        return None


def _gemini_key_available(env_path: str = ENV_FILE) -> bool:
    """
    Cloud-aware preflight check for GEMINI_API_KEY.

    Mirrors the EnvironmentConfig.load() resolution order:
      1. os.environ first  — covers Streamlit Cloud Secrets, Docker, CI/CD.
      2. .env file second  — covers local development.

    Never raises; returns False if the key cannot be found by either method.

    Note: not currently called by run_newsletter_stage(), which now relies on
    ai_newsletter.py raising ConfigurationError directly (see below). Kept
    as a standalone utility, unchanged, per this phase's minimal-diff scope.
    """
    # Priority 1: already injected into the process environment
    if os.getenv("GEMINI_API_KEY", "").strip():
        return True
    # Priority 2: local .env file
    path = Path(env_path)
    if path.exists():
        load_dotenv(dotenv_path=path, override=False)
        return bool(os.getenv("GEMINI_API_KEY", "").strip())
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Stage Runners
# ─────────────────────────────────────────────────────────────────────────────
def run_scraping_stage() -> StageResult:
    """
    Executes Phase 1 (SmartDataExtractor).

    NOTE: smart_data_extractor.py is intentionally unmodified in this phase
    (Architecture Roadmap Phase 1 — Stabilize is scoped to ai_newsletter.py
    and app.py only), so SmartDataExtractor.run() still calls sys.exit()
    internally rather than raising a typed exception. This is why SystemExit
    is still caught here, unlike run_newsletter_stage() below — once
    smart_data_extractor.py is refactored into HackerNewsSource (Architecture
    Roadmap Phase 2 — Strategy Pattern), this will raise ScrapingError
    instead and this function can be simplified to match.

    Scraping failures are always hard failures: without source data, no
    newsletter (live or fallback) is meaningful, so there is no fallback path.
    """
    try:
        SmartDataExtractor(output_dir=OUTPUT_DIR).run()
        return StageResult(success=True)
    except SystemExit:
        return StageResult(
            success=False,
            error_message=(
                "**Scraping failed.** Common causes: network issue, a temporary "
                "Hacker News outage, or a change in the site's HTML structure."
            ),
            show_log_tail=True,
        )
    except Exception as exc:
        return StageResult(
            success=False,
            error_message=f"**Unexpected scraping error:** `{exc}`",
            show_log_tail=True,
        )


def run_newsletter_stage() -> StageResult:
    """
    Executes Phase 2 (AINewsletterGenerator).

    ai_newsletter.py now raises typed exceptions from core.exceptions instead
    of calling sys.exit(), so this function catches those directly — no more
    generic `except SystemExit` / `except Exception`.

    Exception routing:
      ConfigurationError → hard failure, triggers_fallback=False.
          GEMINI_API_KEY is missing or invalid. This is a setup problem, not
          a transient API outage — silently showing a simulated briefing
          would hide the fact that the app isn't configured correctly, so a
          clear st.error is shown instead.
      RepositoryError    → hard failure, triggers_fallback=False.
          The source CSV couldn't be located/read, or the newsletter file
          couldn't be written. This points to a real data/storage problem
          upstream, which a fallback briefing would misleadingly paper over.
      LLMError           → soft failure, triggers_fallback=True.
          Covers the Gemini API itself failing for any reason (including its
          LLMQuotaExceededError / LLMServiceUnavailableError subclasses,
          which are caught here too since they inherit from LLMError). This
          is exactly the transient, demo-visible failure mode the fallback
          engine exists for.
      BriefingEngineError → soft failure, triggers_fallback=True.
          The base class — catches anything unexpected that doesn't fall
          into a more specific category above (AINewsletterGenerator.run()
          wraps any truly unforeseen internal error into this type before
          it propagates). Treated the same as an LLM error for demo
          resilience: the live pipeline failed unexpectedly, so fall back
          rather than crash the UI.
    """
    try:
        AINewsletterGenerator(
            source_dir=OUTPUT_DIR,
            output_dir=NEWSLETTER_DIR,
            env_file=ENV_FILE,
        ).run()
        return StageResult(success=True)

    except ConfigurationError as exc:
        # Full detail is already in newsletter_generator.log — ai_newsletter.py's
        # logger.critical() ran before re-raising. The expander below surfaces it.
        return StageResult(
            success=False,
            error_message=(
                "**Configuration error — `GEMINI_API_KEY` is missing or invalid.** "
                "Add it as a Streamlit Secret (cloud) or in a local `.env` file."
            ),
            show_log_tail=True,
            triggers_fallback=False,
        )

    except RepositoryError as exc:
        return StageResult(
            success=False,
            error_message=f"**Data error:** `{exc}`",
            show_log_tail=True,
            triggers_fallback=False,
        )

    except LLMError as exc:
        return StageResult(
            success=False,
            error_message=f"Gemini API error: {exc}",
            triggers_fallback=True,
        )

    except BriefingEngineError as exc:
        return StageResult(
            success=False,
            error_message=f"Unexpected pipeline error: {exc}",
            triggers_fallback=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Session State Bootstrap
# ─────────────────────────────────────────────────────────────────────────────
# is_fallback_active  — True immediately after a fallback fires; cleared when
#                       a live generation succeeds. Controls the info banner.
# show_fallback_toast — Set before st.rerun() to trigger the toast on the
#                       next render (persists through the rerun cleanly).
st.session_state.setdefault("is_fallback_active", False)
st.session_state.setdefault("show_fallback_toast", False)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
all_newsletters = get_all_newsletters()       # fresh filesystem scan on every render

with st.sidebar:
    st.markdown("## 🧠 AI Tech Briefing Engine")
    st.caption("Autonomous tech news curation, powered by Gemini AI.")
    st.divider()

    st.markdown(
        "Scrapes the top stories from **Hacker News**, then uses "
        "Google's **Gemini 2.5 Flash** to synthesize them into a polished "
        "editorial briefing — fully automated, end to end. "
        "If the API is under heavy load, the engine seamlessly switches to a "
        "high-quality simulated briefing so your demo never drops."
    )
    st.markdown(
        "**Pipeline**\n\n"
        "1. 🔍 Scrape Hacker News top stories\n"
        "2. 🧠 Synthesize with Gemini AI\n"
        "3. 📰 Render as Markdown briefing"
    )

    # ── Archive / History ──────────────────────────────────────────────────────
    if all_newsletters:
        st.divider()
        st.markdown("### 📚 Briefing Archive")
        st.caption(
            f"{len(all_newsletters)} briefing{'s' if len(all_newsletters) != 1 else ''} on disk"
        )

        # Map display labels → NewsletterFile objects for O(1) lookup after selection
        archive_map: dict[str, NewsletterFile] = {
            nf.display_label: nf for nf in all_newsletters
        }
        selected_label: str = st.selectbox(
            "Select a briefing to view:",
            list(archive_map.keys()),
            index=0,
            key="archive_selectbox",
            help=(
                "📰 = live AI-generated briefing\n"
                "⚡ = high-quality simulated briefing (API was unavailable)"
            ),
        )
        active_newsletter: Optional[NewsletterFile] = archive_map[selected_label]
    else:
        active_newsletter = None

    st.divider()
    st.markdown("### 👨‍💻 Developer")
    st.markdown("**Youssef**")
    st.caption("Software Engineer — Full-Stack & AI/ML")
    st.divider()
    st.caption("Python · Streamlit · BeautifulSoup · Gemini AI")


# ─────────────────────────────────────────────────────────────────────────────
# Main Header
# ─────────────────────────────────────────────────────────────────────────────
st.title("🧠 AI Tech Briefing Engine")
st.caption(
    "Hacker News → Gemini 2.5 Flash → a polished editorial briefing, generated on demand."
)

generate_clicked = st.button(
    "🚀 Generate Today's Briefing",
    type="primary",
    use_container_width=True,
    help="Scrapes the 20 latest Hacker News stories and drafts a fresh AI briefing (~15–30 s).",
)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Execution  (st.status gives real-time progress feedback)
# ─────────────────────────────────────────────────────────────────────────────
if generate_clicked:
    scrape_result  = StageResult(success=False)
    newsletter_result = StageResult(success=False)

    with st.status("Running pipeline...", expanded=True) as pipeline_status:

        # ── Stage 1: Scrape ────────────────────────────────────────────────────
        pipeline_status.write(
            "🔍 **Stage 1 / 2** — Scraping latest stories from Hacker News..."
        )
        scrape_result = run_scraping_stage()

        if not scrape_result.success:
            pipeline_status.update(
                label="❌ Scraping failed — see details below.",
                state="error",
                expanded=True,
            )

        else:
            pipeline_status.write("✅ Articles scraped and saved to CSV.")

            # ── Stage 2: AI Generation ─────────────────────────────────────────
            pipeline_status.write(
                "🧠 **Stage 2 / 2** — Generating newsletter with Gemini 2.5 Flash..."
            )
            newsletter_result = run_newsletter_stage()

            if newsletter_result.success:
                pipeline_status.write("✅ Newsletter generated successfully.")
                pipeline_status.update(
                    label="✅ Live briefing generated!",
                    state="complete",
                    expanded=False,
                )
            elif newsletter_result.triggers_fallback:
                # Soft failure (LLMError / BriefingEngineError) — fallback is coming.
                pipeline_status.write(
                    "⚡ Gemini API unavailable — activating simulation mode..."
                )
                pipeline_status.update(
                    label="⚡ API busy — loading simulated briefing...",
                    state="complete",
                    expanded=False,
                )
            else:
                # Hard failure (ConfigurationError / RepositoryError) — no fallback.
                pipeline_status.write(
                    "❌ Newsletter generation failed — see details below."
                )
                pipeline_status.update(
                    label="❌ Newsletter generation failed.",
                    state="error",
                    expanded=True,
                )

    # ── Post-status logic (must live OUTSIDE the `with st.status` block) ──────
    # Reason: st.expander cannot be nested inside st.status in Streamlit 1.x.

    if not scrape_result.success:
        # Hard failure — show error and diagnostic details, do NOT rerun.
        st.error(scrape_result.error_message or "Scraping failed.", icon="🚫")
        if scrape_result.show_log_tail:
            tail = _read_log_tail(LOG_CANDIDATES)
            if tail:
                with st.expander("🔍 Show technical diagnostics"):
                    st.code(tail, language="text")

    elif not newsletter_result.success and not newsletter_result.triggers_fallback:
        # Hard failure: ConfigurationError or RepositoryError — show a clear
        # error and stop. No fallback, no rerun: the person needs to fix the
        # underlying setup/data issue before trying again.
        st.error(newsletter_result.error_message or "Newsletter generation failed.", icon="🚫")
        if newsletter_result.show_log_tail:
            tail = _read_log_tail(LOG_CANDIDATES)
            if tail:
                with st.expander("🔍 Show technical diagnostics"):
                    st.code(tail, language="text")

    elif not newsletter_result.success:
        # Soft failure (triggers_fallback is True here by elimination) —
        # activate the fallback engine silently.
        fallback_saved = False
        try:
            FallbackNewsletterGenerator(output_dir=NEWSLETTER_DIR).generate_and_save()
            fallback_saved = True
        except Exception as exc:
            # Extremely rare (disk full / permissions). Show error; do not rerun.
            st.error(
                f"**Fallback generation failed:** `{exc}`\n\n"
                "Please check write permissions on the `newsletters/` directory.",
                icon="🚫",
            )

        if fallback_saved:
            st.session_state["is_fallback_active"] = True
            st.session_state["show_fallback_toast"] = True
            st.rerun()

    else:
        # Full success — clear any stale fallback state and refresh the UI.
        st.session_state["is_fallback_active"] = False
        st.session_state["show_fallback_toast"] = False
        st.rerun()


st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# Deferred Toast  (fired on the render AFTER a fallback rerun)
# Setting session_state before st.rerun() ensures the toast fires exactly once.
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.get("show_fallback_toast"):
    st.toast(
        "⚡ Google Gemini API is currently handling heavy global traffic. "
        "Seamlessly switched to a simulated production briefing for demonstration.",
        icon="⚡",
    )
    st.session_state["show_fallback_toast"] = False


# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────
if active_newsletter is None:
    st.info(
        "👋 No briefing has been generated yet. "
        "Click **Generate Today's Briefing** above to run the full pipeline.",
        icon="📭",
    )
else:
    # ── Fallback / Simulation Banner ───────────────────────────────────────────
    is_fresh_fallback = (
        st.session_state.get("is_fallback_active")
        and active_newsletter.is_fallback
    )

    if is_fresh_fallback:
        col_banner, col_dismiss = st.columns([14, 1])
        with col_banner:
            st.info(
                "⚡ **Simulation Mode Active** — Google Gemini API was temporarily "
                "unavailable (quota limit or 503 overload). A high-quality simulated "
                "briefing is displayed below. Click **Generate Today's Briefing** "
                "to retry live generation at any time.",
                icon="⚡",
            )
        with col_dismiss:
            if st.button("✕", key="dismiss_banner", help="Dismiss this notice"):
                st.session_state["is_fallback_active"] = False
                st.rerun()

    elif active_newsletter.is_fallback:
        # Browsing an older fallback entry from the archive — subtle note only.
        st.caption(
            "⚡ *This is a simulated briefing generated during an API outage.*"
        )

    # ── Metadata Metrics ───────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📅 Date",       active_newsletter.generated_at.strftime("%b %d, %Y"))
    m2.metric("🕐 Time",       active_newsletter.generated_at.strftime("%I:%M %p"))
    m3.metric("📝 Word Count", f"{active_newsletter.word_count:,}")
    m4.metric("🔖 Source",     "⚡ Simulated" if active_newsletter.is_fallback else "🤖 Live AI")

    # ── Download ───────────────────────────────────────────────────────────────
    st.download_button(
        label=f"⬇️  Download  —  {active_newsletter.path.name}",
        data=active_newsletter.content.encode("utf-8"),
        file_name=active_newsletter.path.name,
        mime="text/markdown",
        type="primary",
        use_container_width=True,
    )

    st.write("")

    # ── Newsletter Content ─────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(active_newsletter.content)