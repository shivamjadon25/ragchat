import streamlit as st
import google.generativeai as genai
import os
import json
import time
from urllib.parse import urlparse
from supabase import create_client, Client

# Set page configuration to centered (prevents wide-stretching)
st.set_page_config(
    page_title="Customer Chatbot Support",
    page_icon="💬",
    layout="centered"
)

# Settings File Path
SETTINGS_FILE = "/home/user/Documents/Projects/chatbot/bot_settings.json"

def load_bot_settings(bot_id):
    default_settings = {
        "model_name": "models/gemini-2.5-flash",
        "system_prompt": "",
        "temperature": 0.7,
        "top_p": 0.95,
        "max_output_tokens": 1024
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                all_settings = json.load(f)
                return all_settings.get(bot_id, default_settings)
        except:
            pass
    return default_settings

# Helper: Initialize Supabase
def get_supabase_client(url, key):
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

# Load API credentials from environment/secrets
sb_url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
sb_key = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))
gemini_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

# Sidebar Config for keys overriding
with st.sidebar:
    st.subheader("⚙️ Config Panel")
    sb_url_in = st.text_input("Supabase Project URL:", value=sb_url, placeholder="https://xxxx.supabase.co")
    sb_key_in = st.text_input("Supabase API Key:", type="password", value=sb_key, placeholder="eyJhbG...")
    gemini_key_in = st.text_input("Gemini API Key:", type="password", value=gemini_key, placeholder="AIzaSy...")
    
    # Override defaults if input is provided
    if sb_url_in: sb_url = sb_url_in
    if sb_key_in: sb_key = sb_key_in
    if gemini_key_in: gemini_key = gemini_key_in

# Validate credentials
if not sb_url or not sb_key or not gemini_key:
    st.info("⚠️ Please enter Supabase & Gemini API Keys in the sidebar to load the client chatbot.")
    st.stop()

supabase = get_supabase_client(sb_url, sb_key)
if not supabase:
    st.stop()

# ----------------- PARSE BOT ID -----------------
bot_id = st.query_params.get("botId")

# Fallback: If no botId in URL, fetch available bots so demo testers can select one
if not bot_id:
    try:
        bots_res = supabase.table("bots").select("*").execute()
        available_bots = bots_res.data
    except Exception as e:
        st.error(f"Error fetching chatbots: {e}")
        available_bots = []
        
    if not available_bots:
        st.title("🤖 Chatbot Client")
        st.warning("No chatbots have been created in the Admin Portal yet. Please create a bot first.")
        st.stop()
    else:
        st.info("💡 Tip: You can pass a specific bot via URL like `?botId=your-bot-id`. Showing fallback selection for demo:")
        bot_names_map = {b["name"]: b["id"] for b in available_bots}
        selected_name = st.selectbox("Select Chatbot to Test:", list(bot_names_map.keys()))
        bot_id = bot_names_map[selected_name]

# Fetch details of selected bot
try:
    bot_res = supabase.table("bots").select("*").eq("id", bot_id).execute()
    bot_info = bot_res.data[0] if bot_res.data else None
except Exception as e:
    st.error(f"Error loading bot configuration: {e}")
    st.stop()

if not bot_info:
    st.error(f"Chatbot with ID '{bot_id}' does not exist.")
    st.stop()

# Initialize Chat Session State
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "current_bot_id" not in st.session_state or st.session_state.current_bot_id != bot_id:
    st.session_state.chat_history = []
    st.session_state.conversation_id = None
    st.session_state.current_bot_id = bot_id

# Establish Conversation Session in DB
if st.session_state.conversation_id is None:
    try:
        conv_res = supabase.table("conversations").insert({"bot_id": bot_id}).execute()
        st.session_state.conversation_id = conv_res.data[0]["id"]
    except Exception as e:
        st.error(f"Error starting conversation session in database: {e}")
        st.stop()

# ----------------- SESSION INACTIVITY TIMEOUT -----------------
TIMEOUT_SECONDS = 300  # 5 minutes
current_time = time.time()

if "last_activity" not in st.session_state:
    st.session_state.last_activity = current_time

# Check for timeout expiry
elapsed_inactivity = current_time - st.session_state.last_activity
if elapsed_inactivity > TIMEOUT_SECONDS:
    st.session_state.chat_history = []
    st.session_state.conversation_id = None
    st.session_state.chat_open = False
    try:
        conv_res = supabase.table("conversations").insert({"bot_id": bot_id}).execute()
        st.session_state.conversation_id = conv_res.data[0]["id"]
    except:
        pass
    st.warning("⏱️ Your previous conversation session expired due to 5 minutes of inactivity.")

# Update the active timestamp
st.session_state.last_activity = current_time

# Ensure Welcome Message exists in history
if not st.session_state.chat_history:
    welcome_text = f"Hello! Welcome to {bot_info['name']} support. How can I help you today?"
    st.session_state.chat_history.append({"role": "assistant", "content": welcome_text})

# Inject Custom CSS for beautiful minimal inline widget
st.markdown("""
<style>
    /* Style the inline container wrapper */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.chat-widget-marker) {
        border-radius: 12px !important;
        background-color: var(--secondary-background-color) !important;
        border: 1px solid rgba(128, 128, 128, 0.15) !important;
        padding: 12px !important;
    }

    /* Tighten vertical layout spacing inside the widget */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.chat-widget-marker) [data-testid="stVerticalBlock"] {
        gap: 6px !important;
    }

    /* Styling for the floating FAB button */
    .floating-btn-container {
        position: fixed;
        bottom: 30px;
        right: 30px;
        z-index: 9999;
    }
    .floating-btn-container button {
        background-color: #007bff !important;
        color: white !important;
        border-radius: 50% !important;
        width: 65px !important;
        height: 65px !important;
        font-size: 30px !important;
        box-shadow: 0 5px 15px rgba(0, 123, 255, 0.3) !important;
        border: none !important;
        cursor: pointer !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        transition: transform 0.2s ease !important;
    }
    .floating-btn-container button:hover {
        transform: scale(1.06) !important;
    }

    /* Style header titles to have zero margin */
    .chat-header-title {
        margin: 0 !important;
        padding: 0 !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        line-height: 1.2 !important;
        color: var(--text-color);
    }
    .chat-header-status {
        margin: 0 !important;
        padding: 0 !important;
        font-size: 0.72rem !important;
        font-weight: 600 !important;
        color: #28a745 !important;
    }

    /* macOS style window control header buttons (compact 20px) */
    .min-btn-wrapper button {
        border-radius: 50% !important;
        width: 20px !important;
        height: 20px !important;
        min-height: unset !important;
        padding: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        background-color: rgba(128, 128, 128, 0.12) !important;
        border: none !important;
        font-size: 8px !important;
        font-weight: bold !important;
        color: var(--text-color) !important;
        margin-top: 10px !important;
        transition: background-color 0.2s !important;
    }
    .min-btn-wrapper button:hover {
        background-color: rgba(128, 128, 128, 0.25) !important;
    }

    .close-btn-wrapper button {
        border-radius: 50% !important;
        width: 20px !important;
        height: 20px !important;
        min-height: unset !important;
        padding: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        background-color: rgba(220, 53, 69, 0.12) !important;
        border: none !important;
        font-size: 8px !important;
        font-weight: bold !important;
        color: #dc3545 !important;
        margin-top: 10px !important;
        transition: background-color 0.2s !important;
    }
    .close-btn-wrapper button:hover {
        background-color: rgba(220, 53, 69, 0.25) !important;
    }

    /* Style starter pill buttons */
    .starter-btn button {
        border-radius: 18px !important;
        border: 1px solid rgba(128, 128, 128, 0.15) !important;
        background-color: var(--background-color) !important;
        color: var(--text-color) !important;
        padding: 5px 12px !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
        text-align: left !important;
        margin-bottom: 2px !important;
    }
    .starter-btn button:hover {
        border-color: #007bff !important;
        color: #007bff !important;
        background-color: rgba(0, 123, 255, 0.05) !important;
    }
</style>
""", unsafe_allow_html=True)

# Helper function to render self-contained differentiable chat bubbles natively
def render_custom_bubble(role, content, sources=None):
    if role == "user":
        st.html(
            f"""
            <div style='display: flex; justify-content: flex-end; margin-bottom: 8px;'>
                <div style='background-color: #007bff; color: white; padding: 10px 14px; border-radius: 14px 14px 0px 14px; max-width: 85%; font-size: 0.9rem; line-height: 1.45;'>
                    {content}
                </div>
            </div>
            """
        )
    else:
        sources_html = ""
        if sources:
            sources_html = "<div style='display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;'>"
            for src_url, similarity in sources:
                domain = urlparse(src_url).netloc or "Documentation"
                sources_html += f"<a href='{src_url}' target='_blank' style='text-decoration:none; color:#0056b3; background-color:rgba(0,123,255,0.04); padding:2px 6px; border-radius:6px; font-size:0.68rem;'>🔗 {domain}</a>"
            sources_html += "</div>"
            
        st.html(
            f"""
            <div style='display: flex; justify-content: flex-start; margin-bottom: 8px;'>
                <div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.14); padding: 10px 14px; border-radius: 14px 14px 14px 0px; max-width: 85%; font-size: 0.9rem; line-height: 1.45;'>
                    <div>{content}</div>
                    {sources_html}
                </div>
            </div>
            """
        )

# Initialize Open State
if "chat_open" not in st.session_state:
    st.session_state.chat_open = False

# Render columns split if chat widget is open
if st.session_state.chat_open:
    col_web, col_chat = st.columns([6.5, 3.5])
else:
    col_web = st.container()
    col_chat = None

# Render Website Layout (Always centered in background, no wide stretching)
with col_web:
    st.markdown(f"<h1 style='font-size:2.4rem; font-weight:700; margin-bottom:0;'>🏢 {bot_info['name']}</h1>", unsafe_allow_html=True)
    if bot_info['website_url']:
        st.caption(f"Official Portal: [{bot_info['website_url']}]({bot_info['website_url']})")
    st.markdown("---")
    st.write("Welcome to our simple web portal. Feel free to browse around or activate the support agent in the bottom right corner.")

# Render Chat Widget Window (As Inline Column, no floating container overlay)
if st.session_state.chat_open and col_chat is not None:
    with col_chat:
        with st.container(border=True):
            st.markdown('<div class="chat-widget-marker"></div>', unsafe_allow_html=True)
            
            # Widget Header Row
            hdr_c1, hdr_c2, hdr_c3 = st.columns([8, 1, 1])
            with hdr_c1:
                st.html(
                    f"""
                    <div style='margin-bottom: 0;'>
                        <div class='chat-header-title'>🤖 {bot_info['name']}</div>
                        <div class='chat-header-status'>● Online</div>
                    </div>
                    """
                )
            with hdr_c2:
                st.markdown('<div class="min-btn-wrapper">', unsafe_allow_html=True)
                if st.button("─", key="minimize_chat_widget", help="Minimize Chat (Keeps History)"):
                    st.session_state.chat_open = False
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            with hdr_c3:
                st.markdown('<div class="close-btn-wrapper">', unsafe_allow_html=True)
                if st.button("✕", key="close_chat_session", help="Close Chat (Resets Session & History)"):
                    st.session_state.chat_history = []
                    st.session_state.conversation_id = None
                    st.session_state.chat_open = False
                    st.session_state.last_activity = time.time()
                    try:
                        conv_res = supabase.table("conversations").insert({"bot_id": bot_id}).execute()
                        st.session_state.conversation_id = conv_res.data[0]["id"]
                    except:
                        pass
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
                
            st.html("<hr style='margin: 6px 0; border: 0; border-top: 1px solid rgba(128,128,128,0.15);'/>")
            
            # Scrollable chat logs container (reduced height to fit widget nicely)
            chat_container = st.container(height=310)
            with chat_container:
                for msg in st.session_state.chat_history:
                    render_custom_bubble(msg["role"], msg["content"], msg.get("sources"))
                
                # Show starters inside container if history only contains welcome message
                if len(st.session_state.chat_history) <= 1:
                    st.markdown("<p style='font-size:0.78rem; opacity:0.8; margin-top:10px; margin-bottom:4px; font-weight:600;'>💡 Suggestions:</p>", unsafe_allow_html=True)
                    starters = [
                        "What services do you offer?",
                        "How do I contact support?",
                        "Summarize the main features."
                    ]
                    for idx, q in enumerate(starters):
                        st.markdown('<div class="starter-btn">', unsafe_allow_html=True)
                        if st.button(q, key=f"starter_q_{idx}", use_container_width=True):
                            st.session_state.selected_prompt = q
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)

            # Handle Prompt Input
            prompt = None
            if "selected_prompt" in st.session_state and st.session_state.selected_prompt:
                prompt = st.session_state.selected_prompt
                st.session_state.selected_prompt = None
            else:
                prompt_input = st.chat_input("Ask a question...")
                if prompt_input:
                    prompt = prompt_input
                    
            if prompt:
                # Update active timestamp
                st.session_state.last_activity = time.time()
                
                # Display user message instantly in bubble
                with chat_container:
                    render_custom_bubble("user", prompt)
                st.session_state.chat_history.append({"role": "user", "content": prompt})
                
                # Save User message to Database
                try:
                    supabase.table("messages").insert({
                        "conversation_id": st.session_state.conversation_id,
                        "role": "user",
                        "content": prompt
                    }).execute()
                except:
                    pass
                
                # Check for goodbye
                clean_prompt = "".join(c for c in prompt.lower() if c.isalnum() or c.isspace()).strip()
                if clean_prompt in ["bye", "goodbye", "exit", "quit", "bye bye"]:
                    farewell = f"Goodbye! Thank you for contacting {bot_info['name']} support."
                    with chat_container:
                        render_custom_bubble("assistant", farewell)
                    st.session_state.chat_history.append({"role": "assistant", "content": farewell})
                    
                    try:
                        supabase.table("messages").insert({
                            "conversation_id": st.session_state.conversation_id,
                            "role": "assistant",
                            "content": farewell
                        }).execute()
                    except:
                        pass
                    
                    time.sleep(2.0)
                    st.session_state.chat_history = []
                    st.session_state.conversation_id = None
                    st.session_state.chat_open = False
                    st.session_state.last_activity = time.time()
                    st.rerun()

                # 1. RAG Search (Retrieve matching content from Supabase vector index)
                context = ""
                sources = []
                
                with chat_container:
                    with st.spinner("Searching..."):
                        # Generate Embedding for prompt
                        genai.configure(api_key=gemini_key)
                        
                        # Dynamically resolve embedding model name from the user's active API
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

                        try:
                            emb_res = genai.embed_content(
                                model=embedding_model,
                                content=prompt,
                                task_type="retrieval_query"
                            )
                            query_embedding = emb_res['embedding'][:768]
                            
                            # Execute pgvector RPC search in Supabase
                            rpc_res = supabase.rpc("match_documents", {
                                "query_embedding": query_embedding,
                                "match_threshold": 0.25,
                                "match_count": 4,
                                "filter_bot_id": bot_id
                            }).execute()
                            
                            matches = rpc_res.data or []
                            
                            context_parts = []
                            for match in matches:
                                context_parts.append(f"Source URL: {match['url']}\nContent:\n{match['content']}\n---\n")
                                if (match['url'], match['similarity']) not in sources:
                                    sources.append((match['url'], match['similarity']))
                            
                            context = "\n".join(context_parts)
                        except Exception as e:
                            st.error(f"Search retrieval error: {e}")
                
                # 2. Generation using Gemini
                with chat_container:
                    with st.chat_message("assistant"):
                        message_placeholder = st.empty()
                        
                        # Load settings
                        bot_settings = load_bot_settings(bot_id)
                        
                        # Select base model
                        generation_model = bot_settings.get("model_name", "models/gemini-2.5-flash")
                        
                        # Dynamic model fallback if default
                        if generation_model in ["models/gemini-2.5-flash", "models/gemini-1.5-flash", "gemini-2.5-flash", "gemini-1.5-flash"]:
                            try:
                                models = genai.list_models()
                                valid_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
                                for m in ["models/gemini-2.5-flash", "models/gemini-3.5-flash", "models/gemini-1.5-flash"]:
                                    if m in valid_models:
                                        generation_model = m
                                        break
                                else:
                                    flash_models = [m for m in valid_models if "flash" in m]
                                    if flash_models:
                                        generation_model = flash_models[0]
                                    elif valid_models:
                                        generation_model = valid_models[0]
                            except Exception as e:
                                pass
                                
                        # System instruction fallback
                        default_system_prompt = (
                            f"You are a helpful customer support agent representing {bot_info['name']}. "
                            "Your answers should be friendly, conversational, and direct. "
                            "Base your answer ONLY on the provided Context below. If the answer cannot be found in the context, "
                            "politely state that you do not have that information and suggest contacting human support. "
                            "Do not make up facts."
                        )
                        system_instruction = bot_settings.get("system_prompt")
                        if not system_instruction:
                            system_instruction = default_system_prompt
                            
                        generation_config = {
                            "temperature": float(bot_settings.get("temperature", 0.7)),
                            "top_p": float(bot_settings.get("top_p", 0.95)),
                            "max_output_tokens": int(bot_settings.get("max_output_tokens", 1024))
                        }
                        
                        if context:
                            full_prompt = (
                                f"Context about {bot_info['name']}:\n{context}\n\n"
                                f"User Question: {prompt}\n"
                                f"Answer: "
                            )
                        else:
                            full_prompt = (
                                f"Note: No documents or website pages have been ingested for this bot yet. "
                                "Politely inform the user that you are still being configured and do not have access to any knowledge yet.\n"
                                f"User Question: {prompt}\n"
                                f"Answer: "
                            )
                            
                        try:
                            model = genai.GenerativeModel(
                                model_name=generation_model,
                                system_instruction=system_instruction if context else None
                            )
                            
                            # Stream the response inside a structured HTML bubble
                            full_response = ""
                            response_stream = model.generate_content(
                                full_prompt, 
                                generation_config=generation_config,
                                stream=True
                            )
                            for chunk in response_stream:
                                full_response += chunk.text
                                message_placeholder.markdown(
                                    f"<div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.15); padding: 10px 14px; border-radius: 14px; display: inline-block; max-width: 85%; line-height: 1.4;'>{full_response}▌</div>",
                                    unsafe_allow_html=True
                                )
                            
                            # Remove cursor when finished
                            message_placeholder.markdown(
                                f"<div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.15); padding: 10px 14px; border-radius: 14px; display: inline-block; max-width: 85%; line-height: 1.4;'>{full_response}</div>",
                                unsafe_allow_html=True
                            )
                            
                            # Save Assistant response to Session State
                            st.session_state.chat_history.append({
                                "role": "assistant",
                                "content": full_response,
                                "sources": sources
                            })
                            
                            # Save Assistant response to Database
                            supabase.table("messages").insert({
                                "conversation_id": st.session_state.conversation_id,
                                "role": "assistant",
                                "content": full_response
                            }).execute()
                            
                            # Update active timestamp
                            st.session_state.last_activity = time.time()
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"Error generating response: {e}")

# Render Floating Chatbot Logo Trigger Button on the right side
if not st.session_state.chat_open:
    st.markdown('<div class="floating-btn-container">', unsafe_allow_html=True)
    if st.button("💬", key="fab_widget_trigger", help="Open Support Chat"):
        st.session_state.chat_open = True
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
