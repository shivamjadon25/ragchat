import streamlit as st
import google.generativeai as genai
import numpy as np
import pypdf
import os
import time
import requests
import urllib3
import json
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from supabase import create_client, Client

# Disable SSL verification warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set page configuration
st.set_page_config(
    page_title="RAG Chatbot Admin Portal",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Settings File Path (resolved dynamically relative to this script)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(CURRENT_DIR, "bot_settings.json")

def load_bot_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_bot_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        st.error(f"Error saving model settings: {e}")

# Helper: Initialize Supabase Client
def get_supabase_client(url, key):
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

# Helper: Web crawler
def crawl_website(start_url, max_pages=30):
    parsed_start = urlparse(start_url)
    domain = parsed_start.netloc
    
    if not parsed_start.scheme:
        start_url = "https://" + start_url
        parsed_start = urlparse(start_url)
        domain = parsed_start.netloc

    to_visit = [start_url]
    visited = set()
    pages_data = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    crawl_status = st.empty()
    progress_bar = st.progress(0, text="Starting crawler...")
    
    while to_visit and len(visited) < max_pages:
        current_url = to_visit.pop(0)
        parsed_current = urlparse(current_url)
        normalized_url = f"{parsed_current.scheme}://{parsed_current.netloc}{parsed_current.path}"
        
        if normalized_url in visited:
            continue
            
        visited.add(normalized_url)
        crawl_status.text(f"Crawling ({len(visited)}/{max_pages}): {normalized_url}")
        progress_bar.progress(len(visited) / max_pages, text=f"Crawling website...")
        
        try:
            response = requests.get(current_url, headers=headers, timeout=8, verify=False)
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                continue
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            for element in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
                element.decompose()
                
            text = soup.get_text(separator="\n")
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = "\n".join(chunk for chunk in chunks if chunk)
            
            title = soup.title.string.strip() if soup.title else normalized_url
            pages_data.append({
                "source": normalized_url,
                "title": title,
                "text": clean_text
            })
            
            for link in soup.find_all("a", href=True):
                href = link["href"]
                full_url = urljoin(current_url, href)
                parsed_url = urlparse(full_url)
                
                if parsed_url.netloc == domain:
                    clean_link = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
                    if clean_link not in visited and clean_link not in to_visit:
                        if not any(clean_link.lower().endswith(ext) for ext in [".pdf", ".jpg", ".png", ".gif", ".zip", ".mp4", ".mp3", ".doc", ".docx"]):
                            to_visit.append(clean_link)
                            
        except Exception as e:
            st.warning(f"Error crawling {current_url}: {e}")
            
    crawl_status.empty()
    progress_bar.empty()
    return pages_data

# Helper: Split text into chunks
def chunk_text(text, chunk_size=1000, chunk_overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - chunk_overlap
    return chunks

# Helper: Generate embeddings
def generate_embeddings(chunks, api_key):
    genai.configure(api_key=api_key)
    
    embedding_model = "models/text-embedding-004"
    try:
        models = genai.list_models()
        valid_models = [m.name for m in models if 'embedContent' in m.supported_generation_methods]
        for m in ["models/text-embedding-004", "models/embedding-001"]:
            if m in valid_models:
                embedding_model = m
                break
        else:
            if valid_models:
                embedding_model = valid_models[0]
    except Exception as e:
        pass

    embeddings = []
    batch_size = 50
    progress_bar = st.progress(0, text=f"Generating embeddings using {embedding_model}...")
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        try:
            result = genai.embed_content(
                model=embedding_model,
                content=batch,
                task_type="retrieval_document"
            )
            sliced = [emb[:768] for emb in result['embedding']]
            embeddings.extend(sliced)
        except Exception as e:
            st.error(f"Embedding error: {e}")
            return None
        progress_percentage = min(1.0, (i + batch_size) / len(chunks))
        progress_bar.progress(progress_percentage, text=f"Generated {len(embeddings)}/{len(chunks)} embeddings...")
    progress_bar.empty()
    return embeddings

# Inject Custom CSS for beautiful and minimal layout
st.markdown("""
<style>
    /* Styling for metrics cards */
    .metric-card {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.15);
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
        margin-bottom: 20px;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.05);
    }
    .metric-value {
        font-size: 2.25rem;
        font-weight: 700;
        color: var(--primary-color);
        margin-bottom: 4px;
    }
    .metric-label {
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        opacity: 0.8;
        font-weight: 600;
    }
    
    /* Dialogue chat bubble styling for conversation logs */
    .chat-bubble {
        padding: 14px 18px;
        border-radius: 12px;
        margin-bottom: 12px;
        line-height: 1.5;
        font-size: 0.95rem;
        border: 1px solid rgba(128, 128, 128, 0.12);
    }
    .chat-user {
        background-color: rgba(0, 123, 255, 0.08);
        border-left: 4px solid #007bff;
    }
    .chat-assistant {
        background-color: var(--secondary-background-color);
        border-left: 4px solid #28a745;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- SIDEBAR CONFIG & NAVIGATION -----------------
with st.sidebar:
    st.markdown("## ⚙️ Portal Controls")
    
    # Credentials block
    sb_url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
    sb_key = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))
    gemini_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
    
    with st.expander("🔑 Credentials Config", expanded=not (sb_url and sb_key and gemini_key)):
        sb_url_in = st.text_input("Supabase Project URL:", value=sb_url, placeholder="https://xxxx.supabase.co")
        sb_key_in = st.text_input("Supabase API Key:", type="password", value=sb_key, placeholder="eyJhbG...")
        gemini_key_in = st.text_input("Gemini API Key:", type="password", value=gemini_key, placeholder="AIzaSy...")
        
        # Override if inputs given
        if sb_url_in: sb_url = sb_url_in
        if sb_key_in: sb_key = sb_key_in
        if gemini_key_in: gemini_key = gemini_key_in

    st.markdown("---")
    st.markdown("### 🧭 Main Navigation")
    menu = st.radio(
        "Navigation",
        [
            "🏠 Dashboard",
            "📥 Ingestion & Sources",
            "📊 Bot Analytics",
            "💬 Conversation Logs",
            "⚙️ GenAI & Model Settings"
        ],
        label_visibility="collapsed"
    )

# Stop app execution if parameters are missing
if not sb_url or not sb_key or not gemini_key:
    st.title("⚙️ RAG Chatbot Admin Portal")
    st.warning("⚠️ Please configure **Supabase credentials** and **Gemini API Key** in the sidebar to load the portal.")
    st.stop()

supabase = get_supabase_client(sb_url, sb_key)
if not supabase:
    st.stop()

# Helper: Fetch Bots
def fetch_bots():
    try:
        bots_response = supabase.table("bots").select("*").order("created_at", desc=True).execute()
        return bots_response.data or []
    except Exception as e:
        st.error(f"Error retrieving bots: {e}")
        return []

# Helper: Count Documents
def count_documents(bot_id):
    try:
        doc_count_res = supabase.table("documents").select("id", count="exact").eq("bot_id", bot_id).execute()
        return doc_count_res.count if doc_count_res.count is not None else 0
    except:
        return 0

# Dialogue Modal function
@st.dialog("Full Conversation History", width="large")
def view_full_conversation_dialog(conv_id, bot_name):
    try:
        msgs_res = supabase.table("messages").select("*").eq("conversation_id", conv_id).order("created_at", desc=False).execute()
        messages = msgs_res.data or []
    except Exception as e:
        st.error(f"Error loading transcript: {e}")
        return
        
    st.markdown(f"### Chat Session with {bot_name}")
    st.caption(f"Session ID: `{conv_id}`")
    st.markdown("---")
    
    if not messages:
        st.info("No messages in this conversation session.")
    else:
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            created = msg["created_at"][:19].replace("T", " ")
            
            role_label = "👤 User" if role == "user" else "🤖 Assistant"
            class_name = "chat-user" if role == "user" else "chat-assistant"
            
            st.markdown(
                f"<div class='chat-bubble {class_name}'>"
                f"<strong>{role_label}</strong> <span style='font-size:0.8rem; opacity:0.7; float:right;'>{created}</span>"
                f"<div style='margin-top: 6px; white-space: pre-wrap;'>{content}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

# ----------------- NAVIGATION ROUTING -----------------

# 1. DASHBOARD
if menu == "🏠 Dashboard":
    st.markdown("<h1 style='margin-bottom:0;'>🏠 Dashboard</h1>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:1.1rem; opacity:0.8; margin-bottom:2rem;'>Register bots, view status metrics, and overview active resources.</p>", unsafe_allow_html=True)
    
    bots = fetch_bots()
    
    # Load Overview statistics
    total_bots = len(bots)
    total_convs = 0
    total_chunks = 0
    
    try:
        convs_res = supabase.table("conversations").select("id", count="exact").execute()
        total_convs = convs_res.count if convs_res.count is not None else 0
        docs_res = supabase.table("documents").select("id", count="exact").execute()
        total_chunks = docs_res.count if docs_res.count is not None else 0
    except:
        pass
        
    # KPIs Row
    kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
    with kpi_col1:
        st.markdown(
            f"<div class='metric-card'><div class='metric-value'>{total_bots}</div><div class='metric-label'>Active Chatbots</div></div>",
            unsafe_allow_html=True
        )
    with kpi_col2:
        st.markdown(
            f"<div class='metric-card'><div class='metric-value'>{total_convs}</div><div class='metric-label'>Total Conversations</div></div>",
            unsafe_allow_html=True
        )
    with kpi_col3:
        st.markdown(
            f"<div class='metric-card'><div class='metric-value'>{total_chunks}</div><div class='metric-label'>Ingested Text Chunks</div></div>",
            unsafe_allow_html=True
        )
        
    st.markdown("---")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("🤖 Create a New Chatbot")
        with st.form("create_bot_form", clear_on_submit=True):
            bot_id = st.text_input("Bot Unique ID (e.g. acme-corp):", placeholder="letters, numbers, hyphens only").strip().lower()
            bot_name = st.text_input("Bot Name (e.g. Acme Corp Assistant):", placeholder="Enter display name")
            website_url = st.text_input("Website URL (e.g. https://acme.com):", placeholder="Optional website base URL")
            
            submit_bot = st.form_submit_button("Create Chatbot", use_container_width=True)
            
            if submit_bot:
                if not bot_id or not bot_name:
                    st.error("Bot ID and Bot Name are required.")
                elif " " in bot_id:
                    st.error("Bot Unique ID cannot contain spaces.")
                else:
                    try:
                        supabase.table("bots").insert({
                            "id": bot_id,
                            "name": bot_name,
                            "website_url": website_url
                        }).execute()
                        st.success(f"Bot '{bot_name}' successfully created!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error creating bot (check if ID already exists): {e}")
                        
    with col2:
        st.subheader("📋 Registered Chatbots List")
        if not bots:
            st.info("No chatbots registered yet. Create one on the left.")
        else:
            bot_df_data = []
            for b in bots:
                chunks = count_documents(b["id"])
                created_at = b["created_at"][:10] if b["created_at"] else "N/A"
                bot_df_data.append({
                    "Name": b["name"],
                    "ID": b["id"],
                    "Website": b["website_url"] or "None provided",
                    "Ingested Chunks": chunks,
                    "Created At": created_at
                })
            
            df = pd.DataFrame(bot_df_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Quick Delete Bot option
            with st.expander("🔴 Dangerous Zone - Delete Chatbot"):
                bot_names_map = {b["name"]: b["id"] for b in bots}
                selected_del_name = st.selectbox("Select Chatbot to Delete:", list(bot_names_map.keys()), key="del_selectbox")
                selected_del_id = bot_names_map[selected_del_name]
                
                confirm_del = st.checkbox(f"I understand that deleting '{selected_del_name}' removes all conversations and RAG documents.")
                if st.button("Delete Chatbot Completely", type="primary", use_container_width=True):
                    if confirm_del:
                        try:
                            supabase.table("bots").delete().eq("id", selected_del_id).execute()
                            st.success(f"Bot '{selected_del_name}' has been deleted.")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting bot: {e}")
                    else:
                        st.warning("Please check the confirmation box.")

# 2. INGESTION & SOURCES
elif menu == "📥 Ingestion & Sources":
    st.markdown("<h1 style='margin-bottom:0;'>📥 Ingestion & Data Sources</h1>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:1.1rem; opacity:0.8; margin-bottom:2rem;'>Crawl and ingest content to feed the RAG vector database.</p>", unsafe_allow_html=True)
    
    bots = fetch_bots()
    if not bots:
        st.info("Please register a chatbot first on the Dashboard menu.")
    else:
        bot_names_map = {b["name"]: b["id"] for b in bots}
        selected_bot_name = st.selectbox("Select Chatbot to Manage Knowledge:", list(bot_names_map.keys()))
        selected_bot_id = bot_names_map[selected_bot_name]
        selected_bot = next(b for b in bots if b["id"] == selected_bot_id)
        
        doc_count = count_documents(selected_bot_id)
        
        # Display Bot Info card
        st.markdown(
            f"<div style='background-color:var(--secondary-background-color); border:1px solid rgba(128,128,128,0.15); padding:16px; border-radius:10px; margin-bottom:20px;'>"
            f"<strong>Selected Bot ID:</strong> <code>{selected_bot_id}</code> | "
            f"<strong>Base URL:</strong> {selected_bot['website_url'] or 'Not provided'} | "
            f"<strong>Total Chunks in DB:</strong> {doc_count}"
            f"</div>",
            unsafe_allow_html=True
        )
        
        col1, col2 = st.columns([2, 3])
        
        with col1:
            st.subheader("🚀 Crawl & Ingest Webpage")
            default_url = selected_bot["website_url"] or "https://"
            crawl_url = st.text_input("Ingestion Start URL:", value=default_url)
            max_crawl = st.number_input("Max Pages to Crawl:", min_value=1, max_value=100, value=15)
            
            ingest_col1, ingest_col2 = st.columns(2)
            
            with ingest_col1:
                if st.button("🚀 Run Ingestion", use_container_width=True, type="primary"):
                    if not crawl_url or crawl_url == "https://":
                        st.error("Please enter a valid website URL.")
                    else:
                        with st.spinner("Crawling website..."):
                            pages = crawl_website(crawl_url, max_crawl)
                        
                        if not pages:
                            st.error("Could not crawl any pages. Check URL validity.")
                        else:
                            all_chunks = []
                            all_sources = []
                            all_titles = []
                            
                            for page in pages:
                                chunks = chunk_text(page["text"])
                                for chunk in chunks:
                                    all_chunks.append(chunk)
                                    all_sources.append(page["source"])
                                    all_titles.append(page["title"])
                                    
                            if all_chunks:
                                embeddings = generate_embeddings(all_chunks, gemini_key)
                                if embeddings:
                                    db_rows = []
                                    for idx, chunk in enumerate(all_chunks):
                                        db_rows.append({
                                            "bot_id": selected_bot_id,
                                            "url": all_sources[idx],
                                            "content": chunk,
                                            "embedding": embeddings[idx]
                                        })
                                    
                                    with st.spinner("Saving documents to database..."):
                                        try:
                                            batch_size = 50
                                            for j in range(0, len(db_rows), batch_size):
                                                supabase.table("documents").insert(db_rows[j:j + batch_size]).execute()
                                            st.success(f"Successfully ingested {len(all_chunks)} text chunks into the database!")
                                            time.sleep(1.5)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error saving to database: {e}")
                            else:
                                st.error("No valid text extracted to chunk.")
                                
            with ingest_col2:
                if st.button("🗑️ Clear All Ingestion Chunks", use_container_width=True):
                    try:
                        supabase.table("documents").delete().eq("bot_id", selected_bot_id).execute()
                        st.success("Successfully deleted all ingested documents for this bot.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting documents: {e}")
                        
        with col2:
            st.subheader("🔗 Ingested URLs & Sources")
            
            # Fetch URL chunk counts
            try:
                docs_res = supabase.table("documents").select("url").eq("bot_id", selected_bot_id).execute()
                docs_data = docs_res.data or []
                
                if not docs_data:
                    st.info("No pages crawled or ingested yet.")
                else:
                    url_counts = {}
                    for d in docs_data:
                        u = d["url"]
                        url_counts[u] = url_counts.get(u, 0) + 1
                    
                    df_urls = pd.DataFrame([{"URL Source": u, "Chunks": c} for u, c in url_counts.items()])
                    st.dataframe(df_urls, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Error loading ingested sources: {e}")

# 3. BOT ANALYTICS
elif menu == "📊 Bot Analytics":
    st.markdown("<h1 style='margin-bottom:0;'>📊 Bot Analytics & Usage</h1>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:1.1rem; opacity:0.8; margin-bottom:2rem;'>Visualize message volume, conversation history logs, and traffic graphs.</p>", unsafe_allow_html=True)
    
    bots = fetch_bots()
    if not bots:
        st.info("Create a bot first to view analytics.")
    else:
        bot_names_map = {b["name"]: b["id"] for b in bots}
        bot_ids_list = ["All Bots (Combined)"] + list(bot_names_map.values())
        
        selected_perf_bot = st.selectbox("Select Chatbot to View Performance:", bot_ids_list)
        
        # Load analytics
        try:
            # 1. Fetch Conversations
            if selected_perf_bot == "All Bots (Combined)":
                conversations_res = supabase.table("conversations").select("*").execute()
            else:
                conversations_res = supabase.table("conversations").select("*").eq("bot_id", selected_perf_bot).execute()
            conversations = conversations_res.data or []
            total_convs = len(conversations)
            
            # 2. Fetch Messages
            conv_ids = [c["id"] for c in conversations]
            all_msgs = []
            if conv_ids:
                batch_size = 100
                for i in range(0, len(conv_ids), batch_size):
                    batch = conv_ids[i:i+batch_size]
                    messages_res = supabase.table("messages").select("*").in_("conversation_id", batch).execute()
                    if messages_res.data:
                        all_msgs.extend(messages_res.data)
                        
            total_msgs = len(all_msgs)
        except Exception as e:
            st.error(f"Error fetching analytics data: {e}")
            total_convs, total_msgs = 0, 0
            conversations = []
            all_msgs = []
            
        # Display KPIs
        col_k1, col_k2, col_k3 = st.columns(3)
        with col_k1:
            st.markdown(
                f"<div class='metric-card'><div class='metric-value'>{total_convs}</div><div class='metric-label'>Conversations</div></div>",
                unsafe_allow_html=True
            )
        with col_k2:
            st.markdown(
                f"<div class='metric-card'><div class='metric-value'>{total_msgs}</div><div class='metric-label'>Total Messages</div></div>",
                unsafe_allow_html=True
            )
        with col_k3:
            avg_len = round(total_msgs / total_convs, 1) if total_convs > 0 else 0
            st.markdown(
                f"<div class='metric-card'><div class='metric-value'>{avg_len}</div><div class='metric-label'>Avg Messages per Session</div></div>",
                unsafe_allow_html=True
            )
            
        st.markdown("---")
        
        # Display Graphs
        if not conversations:
            st.info("No conversational logs recorded yet.")
        else:
            col_g1, col_g2 = st.columns(2)
            
            # Conversions Volume by Date
            with col_g1:
                df_conv = pd.DataFrame(conversations)
                df_conv["created_at"] = pd.to_datetime(df_conv["created_at"])
                df_conv["date"] = df_conv["created_at"].dt.date
                conv_by_date = df_conv.groupby("date").size().reset_index(name="Conversations")
                
                st.markdown("#### 📈 Daily Conversations Volume")
                st.line_chart(conv_by_date.set_index("date"), use_container_width=True)
                
            # Messages Volume by Date
            with col_g2:
                if all_msgs:
                    df_msg = pd.DataFrame(all_msgs)
                    df_msg["created_at"] = pd.to_datetime(df_msg["created_at"])
                    df_msg["date"] = df_msg["created_at"].dt.date
                    msg_by_date = df_msg.groupby("date").size().reset_index(name="Messages")
                    
                    st.markdown("#### 💬 Daily Message Traffic")
                    st.area_chart(msg_by_date.set_index("date"), use_container_width=True)
                else:
                    st.info("No message records found to display traffic.")
                    
            st.markdown("---")
            
            col_g3, col_g4 = st.columns(2)
            
            # Bot usage distribution (Only if Combined selected)
            with col_g3:
                if selected_perf_bot == "All Bots (Combined)":
                    bot_names = {b["id"]: b["name"] for b in bots}
                    df_conv["bot_name"] = df_conv["bot_id"].map(bot_names)
                    bot_counts = df_conv["bot_name"].value_counts().reset_index(name="Conversations")
                    
                    st.markdown("#### 🤖 Usage Distribution by Bot")
                    st.bar_chart(bot_counts.set_index("bot_name"), use_container_width=True)
                else:
                    # Message Distribution by Role for single bot
                    if all_msgs:
                        df_msg = pd.DataFrame(all_msgs)
                        role_counts = df_msg["role"].value_counts().reset_index(name="Count")
                        role_counts["role"] = role_counts["role"].replace({"user": "👤 User", "assistant": "🤖 Assistant"})
                        
                        st.markdown("#### 🗣️ Communication Share by Role")
                        st.bar_chart(role_counts.set_index("role"), use_container_width=True)
                    else:
                        st.info("No logs to view message communication share.")
                        
            # Distribution of conversation length
            with col_g4:
                if all_msgs:
                    df_msg = pd.DataFrame(all_msgs)
                    session_lengths = df_msg.groupby("conversation_id").size().reset_index(name="Messages Exchanged")
                    length_distribution = session_lengths["Messages Exchanged"].value_counts().reset_index(name="Count")
                    length_distribution.rename(columns={"Messages Exchanged": "Session Length (Messages)"}, inplace=True)
                    
                    st.markdown("#### 📊 Session Length Distribution")
                    st.bar_chart(length_distribution.set_index("Session Length (Messages)"), use_container_width=True)
                else:
                    st.info("No dialogue histories to compute session length distribution.")

# 4. CONVERSATION LOGS
elif menu == "💬 Conversation Logs":
    st.markdown("<h1 style='margin-bottom:0;'>💬 Conversation Transcripts</h1>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:1.1rem; opacity:0.8; margin-bottom:2rem;'>Audit chatbot history transcripts and user messages.</p>", unsafe_allow_html=True)
    
    bots = fetch_bots()
    if not bots:
        st.info("Create a bot first to audit conversation histories.")
    else:
        bot_names_map = {b["name"]: b["id"] for b in bots}
        bot_names_map_reverse = {b["id"]: b["name"] for b in bots}
        
        selected_logs_bot = st.selectbox("Select Chatbot to Inspect Logs:", list(bot_names_map.keys()))
        selected_bot_id = bot_names_map[selected_logs_bot]
        
        # Fetch sessions
        try:
            conversations_res = supabase.table("conversations").select("*").eq("bot_id", selected_bot_id).order("created_at", desc=True).execute()
            conversations = conversations_res.data or []
            
            # Load messages counts
            conv_ids = [c["id"] for c in conversations]
            messages_by_conv = {}
            if conv_ids:
                batch_size = 100
                for i in range(0, len(conv_ids), batch_size):
                    batch = conv_ids[i:i+batch_size]
                    msgs_res = supabase.table("messages").select("id", "conversation_id").in_("conversation_id", batch).execute()
                    msgs_data = msgs_res.data or []
                    for m in msgs_data:
                        c_id = m["conversation_id"]
                        messages_by_conv[c_id] = messages_by_conv.get(c_id, 0) + 1
        except Exception as e:
            st.error(f"Error fetching conversation sessions: {e}")
            conversations = []
            messages_by_conv = {}
            
        if not conversations:
            st.info("No active conversation logs logged yet for this bot.")
        else:
            st.markdown("### Conversation Sessions List")
            st.markdown("Click **🔍 View Transcript** to audit the complete dialogue in a popup modal.")
            
            # List sessions with columns
            col_h1, col_h2, col_h3, col_h4 = st.columns([2, 3, 2, 3])
            with col_h1:
                st.markdown("**Session UUID (Short)**")
            with col_h2:
                st.markdown("**Start Date & Time**")
            with col_h3:
                st.markdown("**Messages Count**")
            with col_h4:
                st.markdown("**Actions**")
            
            st.markdown("---")
            
            for conv in conversations:
                conv_id = conv["id"]
                msg_count = messages_by_conv.get(conv_id, 0)
                created_str = conv["created_at"][:19].replace("T", " ")
                
                col_c1, col_c2, col_c3, col_c4 = st.columns([2, 3, 2, 3])
                with col_c1:
                    st.code(f"{conv_id[:8]}...")
                with col_c2:
                    st.write(created_str)
                with col_c3:
                    st.write(msg_count)
                with col_c4:
                    if st.button("🔍 View Transcript", key=f"btn_view_{conv_id}", use_container_width=True):
                        view_full_conversation_dialog(conv_id, selected_logs_bot)

# 5. GENAI & MODEL SETTINGS
elif menu == "⚙️ GenAI & Model Settings":
    st.markdown("<h1 style='margin-bottom:0;'>⚙️ GenAI Model Configuration</h1>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:1.1rem; opacity:0.8; margin-bottom:2rem;'>Fine-tune generation temperature, persona system prompt instructions, and LLM parameter settings.</p>", unsafe_allow_html=True)
    
    bots = fetch_bots()
    if not bots:
        st.info("Create a bot first to modify model configuration.")
    else:
        bot_names_map = {b["name"]: b["id"] for b in bots}
        selected_settings_bot = st.selectbox("Select Chatbot to Configure Settings:", list(bot_names_map.keys()))
        selected_bot_id = bot_names_map[selected_settings_bot]
        
        # Load settings
        all_settings = load_bot_settings()
        bot_settings = all_settings.get(selected_bot_id, {})
        
        st.markdown("### 🛠️ Model Parameters")
        
        # Select Provider
        current_provider = bot_settings.get("provider", "gemini")
        provider_options = ["gemini", "groq"]
        provider_labels = {"gemini": "Google Gemini (RAG Embeddings)", "groq": "Groq (High-Speed Free Tier)"}
        
        provider_selection = st.selectbox(
            "LLM Provider:",
            provider_options,
            index=provider_options.index(current_provider) if current_provider in provider_options else 0,
            format_func=lambda x: provider_labels[x]
        )
        
        # Select Model based on Provider
        if provider_selection == "gemini":
            model_options = [
                "models/gemini-2.5-flash", 
                "models/gemini-3.5-flash", 
                "models/gemini-2.5-pro"
            ]
            current_model = bot_settings.get("model_name", "models/gemini-2.5-flash")
        else:
            model_options = [
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "gemma2-9b-it",
                "mixtral-8x7b-32768"
            ]
            current_model = bot_settings.get("model_name", "llama-3.3-70b-versatile")
            
        if current_model not in model_options:
            model_options.append(current_model)
            
        model_selection = st.selectbox(
            "LLM Model Name:", 
            model_options, 
            index=model_options.index(current_model)
        )
        
        if provider_selection == "groq":
            st.info("⚡ Groq model selected. Ensure you provide your **Groq API Key** in the chatbot portal sidebar (gives you 14,400 free requests per day!).")
        
        # Prompt configuration
        default_prompt = (
            f"[INSTRUCTION]\n"
            f"You are a helpful customer support agent representing {selected_settings_bot}.\n"
            "- Your answers should be friendly, conversational, and direct.\n"
            "- Base your answer ONLY on the provided Context. If the answer cannot be found in the context, "
            "politely state that you do not have that information and suggest contacting human support.\n"
            "- Do not make up facts.\n"
            "- Output ONLY the final customer-facing response. Do NOT output any chain of thought, reasoning, "
            "notes, drafts, evaluations, self-corrections, or internal planning.\n"
            "[/INSTRUCTION]"
        )
        system_prompt = st.text_area("System Prompt (Persona Instructions):", value=bot_settings.get("system_prompt", default_prompt), height=150)
        
        # SLiders
        temperature = st.slider("Temperature (Creativity):", min_value=0.0, max_value=2.0, value=float(bot_settings.get("temperature", 0.7)), step=0.1)
        top_p = st.slider("Top-P (Nucleus Sampling):", min_value=0.0, max_value=1.0, value=float(bot_settings.get("top_p", 0.95)), step=0.05)
        max_tokens = st.number_input("Max Output Tokens Limit:", min_value=1, max_value=8192, value=int(bot_settings.get("max_output_tokens", 1024)))
        
        save_submit = st.button("💾 Save Configuration Settings", use_container_width=True, type="primary")
        
        if save_submit:
            all_settings[selected_bot_id] = {
                "provider": provider_selection,
                "model_name": model_selection,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "top_p": top_p,
                "max_output_tokens": max_tokens
            }
            save_bot_settings(all_settings)
            st.success("Configuration successfully saved!")
