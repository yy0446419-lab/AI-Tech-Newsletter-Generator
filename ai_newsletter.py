"""
╔══════════════════════════════════════════════════════════════════╗
║           Smart Data Extractor — Phase 2                        ║
║           AI-Powered Newsletter Generator                       ║
║           Model  : gemini-1.5-flash  (Google Generative AI)    ║
║           Input  : output/*.csv  (Phase 1 artifact)            ║
║           Output : newsletters/newsletter_<timestamp>.md        ║
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
from dotenv import load_dotenv

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
    Loads and validates environment variables from a .env file.
    Follows the 12-Factor App principle: config lives in the environment.
    """

    _REQUIRED_KEYS: list[str] = ["GEMINI_API_KEY"]

    def __init__(self, env_file: str = ".env") -> None:
        self._env_path = Path(env_file)

    def load(self) -> dict[str, str]:
        """
        Reads the .env file, populates os.environ, and validates required keys.

        Returns:
            A dict mapping each required key to its value.

        Raises:
            FileNotFoundError: If the .env file does not exist.
            EnvironmentError:  If any required key is absent or empty.
        """
        if not self._env_path.exists():
            raise FileNotFoundError(
                f"'.env' file not found at: {self._env_path.resolve()}\n"
                "  ➜  Create it and add:  GEMINI_API_KEY=your_key_here\n"
                "  ➜  Get a free key at:  https://aistudio.google.com/app/apikey"
            )

        load_dotenv(dotenv_path=self._env_path, override=True)
        logger.info(f"Environment loaded from: {self._env_path.resolve()}")

        config: dict[str, str] = {}
        missing: list[str] = []

        for key in self._REQUIRED_KEYS:
            value = os.getenv(key, "").strip()
            if not value:
                missing.append(key)
            else:
                config[key] = value
                logger.info(f"Config key '{key}' loaded successfully (value masked).")

        if missing:
            raise EnvironmentError(
                f"Missing required environment variable(s): {', '.join(missing)}"
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
            FileNotFoundError: If the directory or any CSV files are missing.
        """
        if not self._source_dir.exists():
            raise FileNotFoundError(
                f"Source directory not found: {self._source_dir.resolve()}\n"
                "  ➜  Run Phase 1 (smart_data_extractor.py) first."
            )

        csv_files = sorted(
            self._source_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not csv_files:
            raise FileNotFoundError(
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
            IOError:    If the file cannot be opened or read.
            ValueError: If no valid rows are found.
        """
        articles: list[ArticleSummary] = []

        try:
            with csv_path.open(mode="r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)

                if reader.fieldnames is None:
                    raise ValueError(f"CSV appears to be empty: {csv_path.name}")

                required_cols = {"rank", "title", "link"}
                missing_cols = required_cols - {c.lower() for c in reader.fieldnames}
                if missing_cols:
                    raise ValueError(
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
            raise IOError(f"Cannot read CSV file '{csv_path.name}': {exc}") from exc

        if not articles:
            raise ValueError(
                f"No valid articles could be parsed from '{csv_path.name}'."
            )

        logger.info(
            f"Read {len(articles)} article(s) from '{csv_path.name}':"
        )
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

    _PERSONA: str = (
        "You are a senior technology journalist with 15 years of experience "
        "writing for publications like MIT Technology Review and Wired. "
        "You specialise in writing sharp, insightful daily briefings that "
        "respect your readers' time while delivering genuine analysis."
    )

    _FORMAT_RULES: str = "\n".join([
        "FORMAT RULES (follow precisely):",
        "  1. Start with a bold Markdown title:  # 🗞️ Daily Tech Briefing — {date}",
        "  2. A 2–3 sentence editorial introduction that sets the day's narrative.",
        "  3. For EACH article:",
        "       ## [Article number]. [Compelling section title you write]",
        "       **Source:** [hyperlinked article title](link)",
        "       A 3–4 sentence analysis covering: what it is, why it matters now,",
        "       and one implication for developers, founders, or tech leaders.",
        "  4. Close with a ## Editor's Note section: 3–4 sentences tying all",
        "     stories into a single forward-looking insight or theme.",
        "  5. End with a horizontal rule and a tagline:  *Briefing generated by",
        "     Smart Data Extractor — AI Newsletter Engine*",
        "",
        "TONE: Professional but not stuffy. Analytical but not dry.",
        "      Think MIT Tech Review meets Morning Brew.",
        "OUTPUT: Raw Markdown only. No code fences. No preamble. No 'Sure!' openers.",
    ])

    def build(self, articles: list[ArticleSummary]) -> str:
        """
        Assembles the final prompt string from persona, format rules, and article data.

        Args:
            articles: List of ArticleSummary objects to include in the newsletter.

        Returns:
            The complete prompt string ready to send to the Gemini API.

        Raises:
            ValueError: If the articles list is empty.
        """
        if not articles:
            raise ValueError("Cannot build prompt: articles list is empty.")

        today_str = datetime.now().strftime("%A, %B %d, %Y")  # e.g. Thursday, June 5, 2025
        article_block = "\n".join(
            f"  {a.rank}. TITLE: {a.title!r}\n     LINK:  {a.link}"
            for a in articles
        )

        prompt = (
            f"{self._PERSONA}\n\n"
            f"{self._FORMAT_RULES}\n\n"
            f"Today's date: {today_str}\n\n"
            "TODAY'S ARTICLES TO COVER:\n"
            f"{article_block}\n\n"
            "Write the complete newsletter now."
        )

        logger.info(
            f"Prompt built: {len(prompt):,} chars | "
            f"{len(articles)} articles | date: {today_str}"
        )
        return prompt


# ─────────────────────────────────────────────────────────────────────────────
# Gemini Client
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Gemini Client (Updated to latest google-genai package)
# ─────────────────────────────────────────────────────────────────────────────
class GeminiClient:
    """
    Wrapper around the modern google-genai SDK.
    Handles model initialisation, generation, and response validation.
    """
    _MODEL_ID: str = "gemini-2.5-flash"  # Using the modern model name

    def __init__(self, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("Gemini API key must not be empty.")
        
        # Initialize the new modern client
        self._client = genai.Client(api_key=api_key)
        logger.info(f"Modern Gemini client ready | model: {self._MODEL_ID}")

    def generate(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        logger.info("Sending request to modern Gemini API — please wait...")

        try:
            # Modern generation call
            response = self._client.models.generate_content(
                model=self._MODEL_ID,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.75,
                    top_p=0.95,
                    max_output_tokens=2048,
                ) 
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        text = response.text
        if not text or not text.strip():
            raise RuntimeError("Gemini returned an empty text body.")

        logger.info(f"Response received: {len(text):,} chars")
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
            ValueError: If content is empty.
            IOError:    If the file cannot be written.
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
            raise


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator — Pipeline Controller
# ─────────────────────────────────────────────────────────────────────────────
class AINewsletterGenerator:
    """
    Facade that coordinates all five pipeline stages in sequence:

        Stage 1 │ EnvironmentConfig       — Load .env, validate API key
        Stage 2 │ LatestCSVReader         — Discover CSV → parse top 5 articles
        Stage 3 │ NewsletterPromptBuilder — Assemble structured Gemini prompt
        Stage 4 │ GeminiClient           — Call Gemini API → receive newsletter
        Stage 5 │ NewsletterExporter     — Persist .md file to disk
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
        """Executes the complete pipeline. Exits with code 1 on any failure."""
        self._print_banner()

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
            prompt = NewsletterPromptBuilder().build(articles)

            # ── Stage 4: AI Generation ────────────────────────────────────────
            newsletter_md = GeminiClient(
                api_key=config["GEMINI_API_KEY"]
            ).generate(prompt)

            # ── Stage 5: Persistence ──────────────────────────────────────────
            output_path = NewsletterExporter(
                output_dir=self._output_dir
            ).export(newsletter_md)

            self._print_summary(newsletter_md, output_path)

        except (FileNotFoundError, EnvironmentError) as exc:
            logger.critical(f"[CONFIG ERROR] {exc}")
            sys.exit(1)
        except (IOError, ValueError) as exc:
            logger.critical(f"[DATA ERROR] {exc}")
            sys.exit(1)
        except RuntimeError as exc:
            logger.critical(f"[AI ERROR] {exc}")
            sys.exit(1)
        except KeyboardInterrupt:
            logger.warning("Pipeline interrupted by user.")
            sys.exit(0)
        except Exception as exc:
            logger.critical(f"[UNEXPECTED ERROR] {exc}", exc_info=True)
            sys.exit(1)

    # ── Private Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _print_banner() -> None:
        logger.info("═" * 66)
        logger.info("  Smart Data Extractor · Phase 2 │ AI Newsletter Generator")
        logger.info("  Engine  : Google Gemini 1.5 Flash")
        logger.info("  Input   : output/*.csv    Output: newsletters/*.md")
        logger.info("═" * 66)

    @staticmethod
    def _print_summary(content: str, saved_path: Path) -> None:
        """Prints a preview of the first lines and the final save location."""
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
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    AINewsletterGenerator(
        source_dir="output",
        output_dir="newsletters",
        env_file=".env",
    ).run()