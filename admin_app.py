import streamlit as st
import google.generativeai as genai
import numpy as np
import pypdf
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from supabase import create_client, Client

# Set page configuration
st.set_page_config(
    page_title="RAG Chatbot Admin Portal",
    page_icon="⚙️",
    layout="wide"
)

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
            response = requests.get(current_url, headers=headers, timeout=8)
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
    embeddings = []
    batch_size = 50
    progress_bar = st.progress(0, text="Generating embeddings...")
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        try:
            result = genai.embed_content(
                model="models/text-embedding-004",
                content=batch,
                task_type="retrieval_document"
            )
            embeddings.extend(result['embedding'])
        except Exception as e:
            st.error(f"Embedding error: {e}")
            return None
        progress_percentage = min(1.0, (i + batch_size) / len(chunks))
        progress_bar.progress(progress_percentage, text=f"Generated {len(embeddings)}/{len(chunks)} embeddings...")
    progress_bar.empty()
    return embeddings

# ----------------- SIDEBAR SETTINGS -----------------
with st.sidebar:
    st.title("🔑 Service Configuration")
    st.markdown("Enter credentials to connect to your database and LLM APIs.")
    
    # Supabase URLs and API Key
    sb_url = st.text_input(
        "Supabase Project URL:",
        value=st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", "")),
        placeholder="https://xxxx.supabase.co"
    )
    
    sb_key = st.text_input(
        "Supabase API Key (service_role or anon):",
        type="password",
        value=st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", "")),
        placeholder="eyJhbG..."
    )
    
    gemini_key = st.text_input(
        "Gemini API Key:",
        type="password",
        value=st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "")),
        placeholder="AIzaSy..."
    )

# Stop app execution if parameters are missing
if not sb_url or not sb_key or not gemini_key:
    st.title("⚙️ RAG Chatbot Admin Portal")
    st.warning("⚠️ Please configure **Supabase credentials** and **Gemini API Key** in the sidebar to load the portal.")
    st.stop()

supabase = get_supabase_client(sb_url, sb_key)
if not supabase:
    st.stop()

# ----------------- MAIN APP TABS -----------------
st.title("⚙️ RAG Chatbot Admin Portal")
st.markdown("Configure chatbots, crawl/ingest websites, and monitor conversation metrics.")

tab1, tab2 = st.tabs(["🤖 Bot Management", "📊 Analytics & Chat Logs"])

with tab1:
    col1, col2 = st.columns([1, 2])
    
    # Column 1: Create a Bot
    with col1:
        st.subheader("Create a New Bot")
        with st.form("create_bot_form", clear_on_submit=True):
            bot_id = st.text_input("Bot Unique ID (e.g. acme-corp):", placeholder="letters, numbers, hyphens only").strip().lower()
            bot_name = st.text_input("Bot Name (e.g. Acme Corp Assistant):", placeholder="Enter display name")
            website_url = st.text_input("Website URL (e.g. https://acme.com):", placeholder="Optional website base URL")
            
            submit_bot = st.form_submit_button("Create Chatbot")
            
            if submit_bot:
                if not bot_id or not bot_name:
                    st.error("Bot ID and Bot Name are required.")
                elif " " in bot_id:
                    st.error("Bot Unique ID cannot contain spaces.")
                else:
                    try:
                        # Insert bot into DB
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

    # Column 2: Manage & Ingest Websites
    with col2:
        st.subheader("Manage Active Bots & RAG Ingestion")
        
        # Load bots
        try:
            bots_response = supabase.table("bots").select("*").order("created_at", desc=True).execute()
            bots = bots_response.data
        except Exception as e:
            st.error(f"Error retrieving bots: {e}")
            bots = []
            
        if not bots:
            st.info("No chatbots registered yet. Create one on the left.")
        else:
            bot_names_map = {bot["name"]: bot["id"] for bot in bots}
            selected_bot_name = st.selectbox("Select Chatbot to Manage:", list(bot_names_map.keys()))
            selected_bot_id = bot_names_map[selected_bot_name]
            
            # Fetch select bot details
            selected_bot = next(b for b in bots if b["id"] == selected_bot_id)
            
            # Get document count
            try:
                doc_count_res = supabase.table("documents").select("id", count="exact").eq("bot_id", selected_bot_id).execute()
                doc_count = doc_count_res.count if doc_count_res.count is not None else 0
            except:
                doc_count = 0
                
            st.write(f"**Bot ID:** `{selected_bot_id}`")
            st.write(f"**Base Website:** {selected_bot['website_url'] or 'Not provided'}")
            st.write(f"**Ingested Chunks in DB:** {doc_count}")
            
            # Direct link to the public chatbot
            # Assumes the chatbot app is running, developer can append URL parameters
            st.markdown(f"🔗 **Client Chatbot URL:** `https://your-chatbot-client.streamlit.app/?botId={selected_bot_id}`")
            
            st.markdown("---")
            
            # Ingestion Control
            st.markdown("#### Ingest Website Content")
            default_url = selected_bot["website_url"] or "https://"
            crawl_url = st.text_input("Ingestion Start URL:", value=default_url, key="crawl_url")
            max_crawl = st.number_value = st.number_input("Max Pages to Crawl:", min_value=1, max_value=100, value=15, key="max_crawl")
            
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("🚀 Crawl & Ingest Now", use_container_width=True):
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
                                    # Prepare rows for insert
                                    db_rows = []
                                    for idx, chunk in enumerate(all_chunks):
                                        db_rows.append({
                                            "bot_id": selected_bot_id,
                                            "url": all_sources[idx],
                                            "content": chunk,
                                            "embedding": embeddings[idx]
                                        })
                                    
                                    # Insert in batches
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
                                
            with col_b2:
                if st.button("🗑️ Clear Ingested Data", use_container_width=True):
                    try:
                        supabase.table("documents").delete().eq("bot_id", selected_bot_id).execute()
                        st.success("Successfully deleted all ingested documents for this bot.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting documents: {e}")
                        
            st.markdown("---")
            # Delete Bot completely
            if st.button("🔴 Delete Chatbot Completely", use_container_width=True):
                try:
                    supabase.table("bots").delete().eq("id", selected_bot_id).execute()
                    st.success(f"Bot '{selected_bot_name}' deleted.")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting bot: {e}")

# ----------------- ANALYTICS & LOGS TAB -----------------
with tab2:
    st.subheader("Chatbot Performance & Logs")
    
    # Load bots list for filter
    try:
        bots_response = supabase.table("bots").select("*").execute()
        bots_list = bots_response.data
    except Exception as e:
        st.error(f"Error: {e}")
        bots_list = []
        
    if not bots_list:
        st.info("Create a bot first to monitor analytics.")
    else:
        bot_ids_list = [bot["id"] for bot in bots_list]
        selected_perf_bot = st.selectbox("Select Bot to View Performance:", bot_ids_list)
        
        # Load Analytics metrics
        try:
            # Get total conversations
            conversations_res = supabase.table("conversations").select("*").eq("bot_id", selected_perf_bot).order("created_at", desc=True).execute()
            conversations = conversations_res.data
            total_convs = len(conversations)
            
            # Get total messages (via join/filter, count messages where conversation's bot_id match)
            # To do this simply, we fetch messages belonging to these conversation IDs
            conv_ids = [c["id"] for c in conversations]
            
            total_msgs = 0
            messages_by_conv = {}
            
            if conv_ids:
                messages_res = supabase.table("messages").select("*").in_("conversation_id", conv_ids).order("created_at", desc=False).execute()
                all_msgs = messages_res.data
                total_msgs = len(all_msgs)
                
                # Group messages by conversation ID
                for msg in all_msgs:
                    c_id = msg["conversation_id"]
                    if c_id not in messages_by_conv:
                        messages_by_conv[c_id] = []
                    messages_by_conv[c_id].append(msg)
        except Exception as e:
            st.error(f"Error fetching analytics data: {e}")
            total_convs, total_msgs = 0, 0
            conversations = []
            messages_by_conv = {}
            
        # Display KPIs
        kpi1, kpi2, kpi3 = st.columns(3)
        with kpi1:
            st.metric("Total Conversations", total_convs)
        with kpi2:
            st.metric("Total Messages Exchanged", total_msgs)
        with kpi3:
            avg_length = round(total_msgs / total_convs, 1) if total_convs > 0 else 0
            st.metric("Avg Messages per Conv", avg_length)
            
        st.markdown("---")
        st.subheader("Conversation History Transcripts")
        
        if not conversations:
            st.info("No client conversations logged yet for this bot.")
        else:
            # Layout: Select conversation on the left, view transcript on the right
            left_col, right_col = st.columns([1, 2])
            
            with left_col:
                st.write("**Conversations List (Newest first)**")
                conv_options = {f"Session {conv['id'][:8]}... (Started {conv['created_at'][:19]})": conv["id"] for conv in conversations}
                selected_conv_label = st.radio("Select Session:", list(conv_options.keys()))
                selected_conv_id = conv_options[selected_conv_label]
                
            with right_col:
                st.write(f"**Session Log:** `{selected_conv_id}`")
                st.markdown("<div style='border:1px solid #ddd; padding:15px; border-radius:5px; background-color:#f9f9f9; max-height:400px; overflow-y:auto;'>", unsafe_allow_html=True)
                
                conv_messages = messages_by_conv.get(selected_conv_id, [])
                if not conv_messages:
                    st.write("No messages in this session.")
                else:
                    for msg in conv_messages:
                        role_label = "**👤 User**" if msg["role"] == "user" else "**🤖 Assistant**"
                        bg_color = "#e6f3ff" if msg["role"] == "user" else "#ffffff"
                        st.markdown(
                            f"<div style='background-color:{bg_color}; padding:10px; margin-bottom:8px; border-radius:4px; border-left: 3px solid #007bff;'>"
                            f"{role_label} <small style='color:gray;'>{msg['created_at'][11:19]}</small><br>"
                            f"{msg['content']}"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                st.markdown("</div>", unsafe_allow_html=True)
