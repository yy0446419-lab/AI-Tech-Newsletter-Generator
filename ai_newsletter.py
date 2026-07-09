"""
╔══════════════════════════════════════════════════════════════════╗
║           Smart Data Extractor — Phase 2                        ║
║           AI-Powered Newsletter Generator                       ║
║           Model  : gemini-2.5-flash  (google-genai SDK)        ║
║           Input  : output/*.csv  (Phase 1 artifact)             ║
║           Output : newsletters/newsletter_<timestamp>.md        ║
║                                                                    ║
║           Architecture Roadmap · Phase 1 — Stabilize:           ║
║             • No sys.exit() outside the CLI entry point below.  ║
║             • All failures raise typed exceptions from           ║
║               core.exceptions — callers decide how to react.    ║
╚══════════════════════════════════════════════════════════════════╝
"""

import csv
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from dotenv import load_dotenv

from core.exceptions import (
    BriefingEngineError,
    ConfigurationError,
    LLMError,
    LLMQuotaExceededError,
    LLMServiceUnavailableError,
    RepositoryError,
)

# ─────────────────────────────────────────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("newsletter_generator.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ArticleSummary:
    """Lightweight, immutable value object for newsletter input data."""

    rank: int
    title: str
    link: str

    def __str__(self) -> str:
        return f"[{self.rank}] {self.title[:70]}"


# ─────────────────────────────────────────────────────────────────────────────
# Environment Configuration
# ─────────────────────────────────────────────────────────────────────────────
class EnvironmentConfig:
    """
    Loads and validates required environment variables with a cloud-first,
    local-fallback strategy.

    Resolution order (12-Factor App + cloud-platform compatible):
      1. os.environ — injected by Streamlit Cloud Secrets, Docker, CI/CD, etc.
      2. .env file  — used for local development only.

    This design guarantees zero-configuration deployment on Streamlit Cloud
    or any platform that pre-populates os.environ, while remaining ergonomic
    for local development via a .env file.
    """

    _REQUIRED_KEYS: list[str] = ["GEMINI_API_KEY"]

    def __init__(self, env_file: str = ".env") -> None:
        self._env_path = Path(env_file)

    def load(self) -> dict[str, str]:
        """
        Resolves all required keys from environment or .env file and returns
        a validated config dict.

        Resolution logic:
          - If ALL required keys are already present in os.environ, the .env
            file is bypassed entirely (cloud-compatible path).
          - If any key is missing from os.environ, the .env file is loaded.
            ConfigurationError is raised only when the file is genuinely
            absent AND the key was not found in the environment.

        Returns:
            A dict mapping each required key to its validated string value.

        Raises:
            ConfigurationError: If a required key cannot be resolved from
                                either os.environ or a local .env file.
        """
        # ── Step 1: Cloud-first check — inspect os.environ before touching disk ──
        prefilled = {k: os.environ.get(k, "").strip() for k in self._REQUIRED_KEYS}
        all_present_in_env = all(prefilled.values())

        if all_present_in_env:
            logger.info(
                "All required keys detected in os.environ — "
                "bypassing .env file (cloud-compatible mode active)."
            )
            for key in self._REQUIRED_KEYS:
                logger.info(f"  Key '{key}' confirmed in environment (value masked).")
            return dict(prefilled)

        # ── Step 2: Local fallback — load .env file ───────────────────────────
        if not self._env_path.exists():
            raise ConfigurationError(
                f"GEMINI_API_KEY not found in os.environ, and no .env file exists at:\n"
                f"  {self._env_path.resolve()}\n\n"
                "  LOCAL  →  Create a .env file:     echo 'GEMINI_API_KEY=your_key' > .env\n"
                "  CLOUD  →  Add a Streamlit Secret:  GEMINI_API_KEY = 'your_key'\n"
                "  KEY    →  Get a free API key at:  https://aistudio.google.com/app/apikey"
            )

        # override=False ensures existing os.environ values (e.g. partial secrets)
        # are never silently overwritten by a stale .env file.
        load_dotenv(dotenv_path=self._env_path, override=False)
        logger.info(f"Environment loaded from: {self._env_path.resolve()}")

        # ── Step 3: Validate after merge ──────────────────────────────────────
        config: dict[str, str] = {}
        missing: list[str] = []

        for key in self._REQUIRED_KEYS:
            value = os.getenv(key, "").strip()
            if not value:
                missing.append(key)
            else:
                config[key] = value
                logger.info(f"  Key '{key}' loaded from .env file (value masked).")

        if missing:
            raise ConfigurationError(
                f"Missing required environment variable(s): {', '.join(missing)}\n"
                "  Ensure the key is set in your .env file or platform secrets."
            )

        return config


# ─────────────────────────────────────────────────────────────────────────────
# CSV Reader
# ─────────────────────────────────────────────────────────────────────────────
class LatestCSVReader:
    """
    Locates the most recently created CSV in a directory and reads
    the top-N rows into ArticleSummary objects.
    """

    def __init__(self, source_dir: str = "output") -> None:
        self._source_dir = Path(source_dir)

    def find_latest(self) -> Path:
        """
        Scans the source directory for CSV files and returns the newest by mtime.

        Returns:
            Path to the most recently modified .csv file.

        Raises:
            RepositoryError: If the directory or any CSV files are missing.
        """
        if not self._source_dir.exists():
            raise RepositoryError(
                f"Source directory not found: {self._source_dir.resolve()}\n"
                "  ➜  Run Phase 1 (smart_data_extractor.py) first."
            )

        csv_files = sorted(
            self._source_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not csv_files:
            raise RepositoryError(
                f"No .csv files found in: {self._source_dir.resolve()}\n"
                "  ➜  Run Phase 1 (smart_data_extractor.py) to generate one."
            )

        latest = csv_files[0]
        logger.info(
            f"Located latest CSV: '{latest.name}'  "
            f"({len(csv_files)} file(s) in directory)"
        )
        return latest

    def read_top(self, csv_path: Path, top_n: int = 5) -> list[ArticleSummary]:
        """
        Reads up to `top_n` rows from a CSV file and returns ArticleSummary list.

        Args:
            csv_path: Path to the source CSV file.
            top_n:    Maximum number of rows to read.

        Returns:
            A list of ArticleSummary dataclasses.

        Raises:
            RepositoryError: If the file cannot be opened, is empty, is
                             missing required columns, or contains no
                             parseable rows.
        """
        articles: list[ArticleSummary] = []

        try:
            with csv_path.open(mode="r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)

                if reader.fieldnames is None:
                    raise RepositoryError(f"CSV appears to be empty: {csv_path.name}")

                required_cols = {"rank", "title", "link"}
                missing_cols = required_cols - {c.lower() for c in reader.fieldnames}
                if missing_cols:
                    raise RepositoryError(
                        f"CSV is missing required columns: {missing_cols}. "
                        f"Found: {list(reader.fieldnames)}"
                    )

                for row_idx, row in enumerate(reader, start=1):
                    if len(articles) >= top_n:
                        break
                    try:
                        articles.append(
                            ArticleSummary(
                                rank=int(row["rank"]),
                                title=row["title"].strip(),
                                link=row["link"].strip(),
                            )
                        )
                    except (KeyError, ValueError, AttributeError) as exc:
                        logger.warning(
                            f"Row {row_idx}: Skipped due to invalid data — {exc}"
                        )

        except IOError as exc:
            raise RepositoryError(f"Cannot read CSV file '{csv_path.name}': {exc}") from exc

        if not articles:
            raise RepositoryError(
                f"No valid articles could be parsed from '{csv_path.name}'."
            )

        logger.info(f"Read {len(articles)} article(s) from '{csv_path.name}':")
        for article in articles:
            logger.info(f"  {article}")

        return articles


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Builder
# ─────────────────────────────────────────────────────────────────────────────
class NewsletterPromptBuilder:
    """
    Constructs a richly-structured prompt that instructs the Gemini model
    to produce a polished Markdown newsletter.
    """

    _SYSTEM_INSTRUCTION: str = (
        "You are a senior technology journalist with 15 years of experience "
        "writing for publications like MIT Technology Review and Wired. "
        "You specialise in writing sharp, insightful daily briefings that "
        "respect your readers' time while delivering genuine analysis. "
        "You respond with raw Markdown only — no code fences, no preamble, "
        "no conversational openers like 'Sure!' or 'Here is your newsletter:'."
    )

    _FORMAT_RULES: str = "\n".join([
        "FORMAT RULES (follow precisely):",
        "  1. Start with:  # 🗞️ Daily Tech Briefing — {date}",
        "  2. A 2–3 sentence editorial introduction that sets the day's narrative.",
        "  3. For EACH article:",
        "       ## [Article number]. [Compelling section title you write]",
        "       **Source:** [hyperlinked article title](link)",
        "       3–4 sentences of analysis: what it is, why it matters now,",
        "       and one concrete implication for developers, founders, or tech leaders.",
        "  4. Close with ## Editor's Note — 3–4 sentences tying all stories",
        "     into a single forward-looking insight or theme.",
        "  5. End with a horizontal rule and:",
        "     *Briefing generated by Smart Data Extractor — AI Newsletter Engine*",
        "",
        "TONE: Professional but not stuffy. Analytical but not dry.",
        "      Think MIT Tech Review meets Morning Brew.",
    ])

    def build(self, articles: list[ArticleSummary]) -> str:
        """
        Assembles the final prompt string from format rules and article data.

        Args:
            articles: List of ArticleSummary objects to include.

        Returns:
            The complete prompt string ready to send to the Gemini API.

        Raises:
            ValueError: If the articles list is empty. This is a caller
                       contract violation (invalid input), not an
                       operational/domain failure, so it deliberately
                       remains a plain ValueError rather than a
                       BriefingEngineError subclass. In the current
                       pipeline this is unreachable — LatestCSVReader
                       already raises RepositoryError before an empty
                       list could ever reach this method — but the guard
                       stays in place for any future caller of this class.
        """
        if not articles:
            raise ValueError("Cannot build prompt: articles list is empty.")

        now = datetime.now()
        today_str = now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y")

        article_block = "\n".join(
            f"  {a.rank}. TITLE: {a.title!r}\n     LINK:  {a.link}"
            for a in articles
        )

        prompt = (
            f"{self._FORMAT_RULES}\n\n"
            f"Today's date: {today_str}\n\n"
            "TODAY'S ARTICLES TO COVER:\n"
            f"{article_block}\n\n"
            "Write the complete newsletter now."
        )

        logger.info(
            f"Prompt built: {len(prompt):,} chars | "
            f"{len(articles)} article(s) | date: {today_str}"
        )
        return prompt

    @property
    def system_instruction(self) -> str:
        """Returns the system instruction string for the Gemini model config."""
        return self._SYSTEM_INSTRUCTION


# ─────────────────────────────────────────────────────────────────────────────
# Gemini Client
# ─────────────────────────────────────────────────────────────────────────────
class GeminiClient:
    """
    Thin, focused wrapper around the google-genai SDK (v2+).

    Migration note: replaces the deprecated google-generativeai package.
    Uses genai.Client for explicit API-key binding and the
    client.models.generate_content() call pattern for full type safety.
    """

    _MODEL_ID: str = "gemini-2.5-flash"

    _GENERATION_CONFIG = genai_types.GenerateContentConfig(
        temperature=0.75,       # Balanced: creative but grounded
        top_p=0.95,
        max_output_tokens=2048,
    )

    def __init__(self, api_key: str, system_instruction: str = "") -> None:
        """
        Raises:
            ConfigurationError: If api_key is empty or whitespace-only —
                               an invalid/missing credential is a
                               configuration problem, not a generic
                               input-validation error.
        """
        if not api_key or not api_key.strip():
            raise ConfigurationError("Gemini API key must not be empty.")

        self._client = genai.Client(api_key=api_key.strip())

        # Merge system instruction into the generation config if provided.
        if system_instruction.strip():
            self._generation_config = genai_types.GenerateContentConfig(
                system_instruction=system_instruction.strip(),
                temperature=self._GENERATION_CONFIG.temperature,
                top_p=self._GENERATION_CONFIG.top_p,
                max_output_tokens=self._GENERATION_CONFIG.max_output_tokens,
            )
        else:
            self._generation_config = self._GENERATION_CONFIG

        logger.info(f"Gemini client ready | model: {self._MODEL_ID}")

    def generate(self, prompt: str) -> str:
        """
        Sends the prompt to the Gemini API and returns the generated text.

        Args:
            prompt: The fully-constructed prompt string.

        Returns:
            The model's text response as a non-empty string.

        Raises:
            ValueError:                 If the prompt is empty (caller
                                        contract violation).
            LLMQuotaExceededError:      HTTP 429 — quota or rate limit hit.
            LLMServiceUnavailableError: HTTP 503 — provider overloaded.
            LLMError:                   Any other API failure, blocked
                                        content, or empty response.
        """
        if not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        logger.info(
            f"Sending request to Gemini API "
            f"({len(prompt):,} chars) — please wait..."
        )

        try:
            response = self._client.models.generate_content(
                model=self._MODEL_ID,
                contents=prompt,
                config=self._generation_config,
            )

        except genai_errors.ClientError as exc:
            code = getattr(exc, "code", None)
            if code == 429:
                raise LLMQuotaExceededError(
                    f"Gemini API quota exceeded (HTTP 429): {exc}\n"
                    "  ➜  Check your usage limits at https://aistudio.google.com"
                ) from exc
            raise LLMError(
                f"Gemini API client error ({code or '4xx'}): {exc}\n"
                "  ➜  Verify your API key and request format."
            ) from exc

        except genai_errors.ServerError as exc:
            code = getattr(exc, "code", None)
            if code == 503:
                raise LLMServiceUnavailableError(
                    f"Gemini API temporarily overloaded (HTTP 503): {exc}\n"
                    "  ➜  Google's servers may be under heavy load. Retry in a few minutes."
                ) from exc
            raise LLMError(
                f"Gemini API server error ({code or '5xx'}): {exc}"
            ) from exc

        except Exception as exc:
            raise LLMError(
                f"Unexpected error communicating with Gemini API: {exc}"
            ) from exc

        # ── Validate response ──────────────────────────────────────────────────
        if not response.candidates:
            feedback = getattr(response, "prompt_feedback", "No feedback available.")
            raise LLMError(
                f"Gemini returned no candidates. "
                f"Prompt feedback: {feedback}"
            )

        candidate = response.candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)

        if finish_reason and finish_reason != genai_types.FinishReason.STOP:
            logger.warning(
                f"Generation ended with non-STOP finish reason: {finish_reason}. "
                f"Safety ratings: {getattr(candidate, 'safety_ratings', 'N/A')}"
            )

        text: str | None = response.text
        if not text or not text.strip():
            raise LLMError(
                f"Gemini returned an empty text body. "
                f"Finish reason: {finish_reason} | "
                f"Safety: {getattr(candidate, 'safety_ratings', 'N/A')}"
            )

        logger.info(
            f"Response received: {len(text):,} chars | "
            f"~{len(text.split()):,} words"
        )
        return text


# ─────────────────────────────────────────────────────────────────────────────
# Newsletter Exporter
# ─────────────────────────────────────────────────────────────────────────────
class NewsletterExporter:
    """Persists the generated Markdown newsletter to a timestamped .md file."""

    _FILENAME_TEMPLATE: str = "newsletter_{timestamp}.md"

    def __init__(self, output_dir: str = "newsletters") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, content: str) -> Path:
        """
        Writes the newsletter content to a new Markdown file.

        Args:
            content: The generated newsletter text (Markdown).

        Returns:
            The resolved Path of the saved file.

        Raises:
            ValueError:      If content is empty (caller contract violation
                             — unreachable in the current pipeline since
                             GeminiClient.generate() never returns empty text).
            RepositoryError: If the file cannot be written to disk.
        """
        if not content.strip():
            raise ValueError("Newsletter content must not be empty.")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self._output_dir / self._FILENAME_TEMPLATE.format(
            timestamp=timestamp
        )

        try:
            filepath.write_text(content, encoding="utf-8")
            logger.info(f"Newsletter saved → {filepath.resolve()}")
            return filepath
        except IOError as exc:
            logger.error(f"Failed to save newsletter: {exc}")
            raise RepositoryError(
                f"Failed to save newsletter to '{filepath}': {exc}"
            ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Printer  (extracted utility — Architecture Roadmap Phase 1, Task 4)
# ─────────────────────────────────────────────────────────────────────────────
class PipelinePrinter:
    """
    Stateless presentation utility for pipeline console output.

    Extracted from AINewsletterGenerator so that class is left to do exactly
    one thing — orchestrate the five pipeline stages (SRP) — while all
    console/log formatting concerns live here instead. `print_banner` is
    intentionally generic (title + arbitrary detail lines) so it can be
    reused by other pipelines; `print_summary` is newsletter-specific, since
    a scraping pipeline's result summary (an article table) has a
    fundamentally different shape than a newsletter's (a content preview).
    """

    @staticmethod
    def print_banner(title: str, lines: list[str]) -> None:
        """Logs a boxed banner with a title and any number of detail lines."""
        logger.info("═" * 66)
        logger.info(f"  {title}")
        for line in lines:
            logger.info(f"  {line}")
        logger.info("═" * 66)

    @staticmethod
    def print_summary(content: str, saved_path: Path) -> None:
        """Prints a preview of the first lines of generated content plus the save location."""
        separator = "─" * 66
        preview = "\n".join(
            f"  {line}" for line in content.splitlines()[:10] if line.strip()
        )
        print(f"\n{separator}")
        print("  📰  NEWSLETTER PREVIEW (first 10 non-empty lines)")
        print(separator)
        print(preview)
        print(f"\n  ... [{len(content):,} chars total]")
        print(separator)
        print(f"  ✔  Saved to: {saved_path.resolve()}")
        print(f"{separator}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator — Pipeline Controller
# ─────────────────────────────────────────────────────────────────────────────
class AINewsletterGenerator:
    """
    Facade that coordinates all five pipeline stages in sequence:

        Stage 1 │ EnvironmentConfig       — Resolve API key (cloud-first)
        Stage 2 │ LatestCSVReader         — Discover CSV → parse top articles
        Stage 3 │ NewsletterPromptBuilder — Assemble structured Gemini prompt
        Stage 4 │ GeminiClient           — Call Gemini 2.5 Flash → newsletter
        Stage 5 │ NewsletterExporter     — Persist .md file to disk

    This class never calls sys.exit(). Every failure mode raises a typed
    exception from core.exceptions; the caller (a CLI entry point, a
    Streamlit callback, or a future FastAPI route handler) decides what to
    do with it.
    """

    _TOP_N: int = 5

    def __init__(
        self,
        source_dir: str = "output",
        output_dir: str = "newsletters",
        env_file: str = ".env",
    ) -> None:
        self._source_dir = source_dir
        self._output_dir = output_dir
        self._env_file = env_file

    def run(self) -> None:
        """
        Executes the complete pipeline.

        Raises:
            ConfigurationError:  GEMINI_API_KEY is missing or invalid.
            RepositoryError:     Source CSV cannot be located/read, or the
                                 generated newsletter cannot be written.
            LLMQuotaExceededError:      Gemini rejected the request (HTTP 429).
            LLMServiceUnavailableError: Gemini is temporarily overloaded (HTTP 503).
            LLMError:            Any other AI generation failure.
            BriefingEngineError: Wraps any other unexpected failure, so
                                 that no raw built-in exception or
                                 KeyboardInterrupt-adjacent noise ever
                                 escapes this method uncategorized.
        """
        PipelinePrinter.print_banner(
            title="Smart Data Extractor · Phase 2 │ AI Newsletter Generator",
            lines=[
                "Engine  : Google Gemini 2.5 Flash  (google-genai SDK v2+)",
                "Input   : output/*.csv    Output: newsletters/*.md",
            ],
        )

        try:
            # ── Stage 1: Environment ──────────────────────────────────────────
            config: dict[str, str] = EnvironmentConfig(
                env_file=self._env_file
            ).load()

            # ── Stage 2: Data Ingestion ───────────────────────────────────────
            reader = LatestCSVReader(source_dir=self._source_dir)
            csv_path = reader.find_latest()
            articles = reader.read_top(csv_path, top_n=self._TOP_N)

            # ── Stage 3: Prompt Assembly ──────────────────────────────────────
            builder = NewsletterPromptBuilder()
            prompt = builder.build(articles)

            # ── Stage 4: AI Generation ────────────────────────────────────────
            newsletter_md = GeminiClient(
                api_key=config["GEMINI_API_KEY"],
                system_instruction=builder.system_instruction,
            ).generate(prompt)

            # ── Stage 5: Persistence ──────────────────────────────────────────
            output_path = NewsletterExporter(
                output_dir=self._output_dir
            ).export(newsletter_md)

            PipelinePrinter.print_summary(newsletter_md, output_path)

        except ConfigurationError as exc:
            logger.critical(f"[CONFIG ERROR] {exc}")
            raise
        except RepositoryError as exc:
            logger.critical(f"[DATA ERROR] {exc}")
            raise
        except LLMError as exc:
            logger.critical(f"[AI ERROR] {exc}")
            raise
        except KeyboardInterrupt:
            logger.warning("Pipeline interrupted by user.")
            raise
        except Exception as exc:
            logger.critical(f"[UNEXPECTED ERROR] {exc}", exc_info=True)
            raise BriefingEngineError(f"Unexpected pipeline failure: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────
# This is now the ONLY place in the file that calls sys.exit(). Every class
# above raises; only the CLI boundary decides that a raised exception means
# "terminate the process with a non-zero status."
if __name__ == "__main__":
    try:
        AINewsletterGenerator(
            source_dir="output",
            output_dir="newsletters",
            env_file=".env",
        ).run()
    except BriefingEngineError as exc:
        logger.critical(f"Pipeline terminated: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)