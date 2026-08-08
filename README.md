# 🚀 AI-Powered Tech Newsletter Generator

An automated pipeline that scrapes technical articles from public sources and leverages **Google Gemini AI** to generate professional, engaging daily newsletters. Built with pure OOP principles in Python.

## 🛠️ Tech Stack & Features
* **Python 3.12** (Strict typing & Modular OOP architecture)
* **Web Scraping:** httpx, asyncio, BeautifulSoup4 (Asynchronous, concurrent fetching)
* **AI Integration:** `google-genai` (Gemini 2.5 Flash for advanced content synthesis)
* **Security:** `python-dotenv` for API key management

## 🧠 How It Works
1. **Extraction:** Scrapes the top trending articles (Title, Link, Points, Comments).
2. **Transformation:** Cleans and exports the data into structured CSV files.
3. **AI Generation:** Ingests the latest CSV, builds a highly engineered prompt, and calls the Gemini API.
4. **Delivery:** Persists the final output as a professionally formatted Markdown (`.md`) briefing.

*Designed for high reliability, modularity, and rapid adaptation to business automation needs.*
## Running with Docker

The entire AI Tech Briefing Engine runs in a single container — no local Python environment needed.

### Prerequisites
- Docker and Docker Compose installed
- A Gemini API key ([get one free](https://aistudio.google.com/app/apikey))

### Setup

1. Create a `.env` file in the project root:
GEMINI_API_KEY=your_key_here


2. Build and start the container:
```bash
   docker-compose up --build
```

3. Open the app at [http://localhost:8501](http://localhost:8501)

### Notes
- `output/` and `newsletters/` are mounted as volumes, so scraped data and generated briefings persist across restarts and rebuilds.
- If you hit a permission error writing to `output/` or `newsletters/` on a Linux host, run `chmod -R 777 output newsletters` locally — the container runs as a non-root user (UID 1000), and host-mounted volume ownership can occasionally mismatch it.
- Stop the container: `docker-compose down`
- Rebuild after a dependency change: `docker-compose up --build`