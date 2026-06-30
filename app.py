import streamlit as st
import os
from pathlib import Path

# استدعاء الكلاسات من أنظمتك الخلفية
from smart_data_extractor import SmartDataExtractor
from ai_newsletter import AINewsletterGenerator

# ─── Page Configuration ───
st.set_page_config(
    page_title="AI Tech Briefing Engine",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Sidebar: Archive & Developer Info ───
with st.sidebar:
    st.markdown("## 🤖 AI Tech Briefing Engine")
    st.caption("Autonomous tech news curation, powered by Gemini 2.5 AI.")
    st.divider()
    
    st.markdown("### 🗄️ Newsletter Archive")
    newsletters_dir = Path("newsletters")
    md_files = []
    if newsletters_dir.exists():
        # جلب كل الملفات وترتيبها من الأحدث للأقدم
        md_files = sorted(newsletters_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    selected_file = None
    if md_files:
        file_names = [f.name for f in md_files]
        selected_name = st.selectbox("View past briefings:", file_names)
        selected_file = next(f for f in md_files if f.name == selected_name)
    else:
        st.info("No newsletters generated yet.")
        
    st.divider()
    st.markdown("### 👨‍💻 Developer\n**Youssef**\nSoftware Engineer")

# ─── Main Content ───
st.title("📰 Daily Tech Briefing Generator")
st.markdown("A highly modular ETL pipeline that scrapes Hacker News and leverages AI to write professional daily briefings.")

if st.button("🚀 Generate Today's Briefing", type="primary", use_container_width=True):
    # 1. Scraping Stage
    with st.status("Fetching latest data from Hacker News...", expanded=True) as status:
        try:
            st.write("Initializing SmartDataExtractor...")
            extractor = SmartDataExtractor(output_dir="output")
            extractor.run()
            status.update(label="Data Extracted Successfully! ✔️", state="complete", expanded=False)
        except SystemExit:
             status.update(label="Extraction Failed. Check your network or Hacker News structure.", state="error")
             st.stop()
        except Exception as e:
            status.update(label=f"Extraction Error: {e}", state="error")
            st.stop()

    # 2. AI Generation Stage
    with st.status("Generating AI Newsletter with Gemini 2.5 Flash...", expanded=True) as status:
        try:
            st.write("Orchestrating AI pipeline...")
            generator = AINewsletterGenerator(
                source_dir="output",
                output_dir="newsletters",
                env_file=".env"
            )
            generator.run()
            status.update(label="Briefing Generated Successfully! ✔️", state="complete", expanded=False)
            st.rerun() # تحديث الصفحة عشان الأرشيف يشوف الملف الجديد
        except SystemExit:
             status.update(label="AI Generation Failed. Check API Key or limits.", state="error")
             st.stop()
        except Exception as e:
            status.update(label=f"AI Error: {e}", state="error")
            st.stop()

# ─── Display Selected Newsletter ───
if selected_file:
    st.divider()
    st.subheader(f"📄 Viewing: {selected_file.name}")
    
    with open(selected_file, "r", encoding="utf-8") as f:
        content = f.read()
        
    with st.container(border=True):
        st.markdown(content)
        
    st.download_button(
        label="📥 Download This Briefing (.md)",
        data=content,
        file_name=selected_file.name,
        mime="text/markdown",
        use_container_width=True
    )