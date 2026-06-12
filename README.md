# 🚀 AI-Powered Tech Newsletter Generator

An automated pipeline that scrapes technical articles from public sources and leverages **Google Gemini AI** to generate professional, engaging daily newsletters. Built with pure OOP principles in Python.

## 🛠️ Tech Stack & Features
* **Python 3.14** (Strict typing & Modular OOP architecture)
* **Web Scraping:** `requests`, `BeautifulSoup4` (with robust error handling)
* **AI Integration:** `google-genai` (Gemini 2.5 Flash for advanced content synthesis)
* **Security:** `python-dotenv` for API key management

## 🧠 How It Works
1. **Extraction:** Scrapes the top trending articles (Title, Link, Points, Comments).
2. **Transformation:** Cleans and exports the data into structured CSV files.
3. **AI Generation:** Ingests the latest CSV, builds a highly engineered prompt, and calls the Gemini API.
4. **Delivery:** Persists the final output as a professionally formatted Markdown (`.md`) briefing.

*Designed for high reliability, modularity, and rapid adaptation to business automation needs.*