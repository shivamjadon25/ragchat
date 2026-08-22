import streamlit as st
import google.generativeai as genai
import os
import json
import time
from urllib.parse import urlparse
from supabase import create_client, Client

# Set page configuration to standard centered layout for background
st.set_page_config(
    page_title="Customer Chatbot Support",
    page_icon="💬",
    layout="centered"
)

# Settings File Path (resolved dynamically relative to this script)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(CURRENT_DIR, "bot_settings.json")

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
groq_key = st.secrets.get("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", ""))

# Sidebar Config for keys overriding
with st.sidebar:
    st.subheader("⚙️ Config Panel")
    sb_url_in = st.text_input("Supabase Project URL:", value=sb_url, placeholder="https://xxxx.supabase.co")
    sb_key_in = st.text_input("Supabase API Key:", type="password", value=sb_key, placeholder="eyJhbG...")
    gemini_key_in = st.text_input("Gemini API Key:", type="password", value=gemini_key, placeholder="AIzaSy...")
    groq_key_in = st.text_input("Groq API Key (Optional):", type="password", value=groq_key, placeholder="gsk_...")
    
    # Override defaults if input is provided
    if sb_url_in: sb_url = sb_url_in
    if sb_key_in: sb_key = sb_key_in
    if gemini_key_in: gemini_key = gemini_key_in
    if groq_key_in: groq_key = groq_key_in

# Validate credentials
if not sb_url or not sb_key:
    st.info("⚠️ Please enter Supabase Project URL & API Key in the sidebar.")
    st.stop()

if not gemini_key and not groq_key:
    st.info("⚠️ Please enter at least one LLM Provider Key (Gemini or Groq) in the sidebar config panel.")
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

# Inject Custom CSS for beautiful minimal floating widget
st.markdown("""
<style>
    /* Float the bordered container containing our class marker */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.chat-widget-marker) {
        position: fixed !important;
        bottom: 110px !important;
        right: 30px !important;
        width: 380px !important;
        height: 580px !important;
        z-index: 99999 !important;
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.1) !important;
        border-radius: 16px !important;
        background-color: var(--secondary-background-color) !important;
        border: 1px solid rgba(128, 128, 128, 0.15) !important;
        padding: 12px !important;
    }

    /* Tighten vertical layout spacing inside the widget */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.chat-widget-marker) [data-testid="stVerticalBlock"] {
        gap: 6px !important;
    }

    /* Force header control buttons inside the second column to align horizontally to the right */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.chat-widget-marker) [data-testid="column"]:nth-child(2) [data-testid="stVerticalBlock"] {
        flex-direction: row !important;
        justify-content: flex-end !important;
        align-items: center !important;
        gap: 6px !important;
    }

    /* Remove column spacing and margins in header */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.chat-widget-marker) [data-testid="column"] {
        padding: 0 !important;
        margin: 0 !important;
    }
    
    /* Styling for the floating FAB button */
    .floating-btn-container {
        position: fixed;
        bottom: 30px;
        right: 30px;
        z-index: 99999;
    }
    .floating-btn-container button {
        background-color: #007bff !important;
        color: white !important;
        border-radius: 50% !important;
        width: 60px !important;
        height: 60px !important;
        font-size: 28px !important;
        box-shadow: 0 4px 12px rgba(0, 123, 255, 0.3) !important;
        border: none !important;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s ease !important;
    }
    .floating-btn-container button:hover {
        transform: scale(1.05) !important;
        background-color: #0069d9 !important;
    }

    /* Style header titles to have zero margin and small height */
    .chat-header-title {
        margin: 0 !important;
        padding: 0 !important;
        font-size: 1.0rem !important;
        font-weight: 700 !important;
        line-height: 1.1 !important;
        color: var(--text-color);
    }
    .chat-header-status {
        margin: 0 !important;
        padding: 0 !important;
        font-size: 0.68rem !important;
        font-weight: 600 !important;
        color: #28a745 !important;
    }

    /* macOS style window control header buttons (compact 18px) */
    .min-btn-wrapper button {
        border-radius: 50% !important;
        width: 18px !important;
        height: 18px !important;
        min-width: 18px !important;
        min-height: unset !important;
        padding: 0 !important;
        background-color: #ffbd2e !important; /* macOS yellow */
        border: none !important;
        font-size: 8px !important;
        font-weight: bold !important;
        color: rgba(0, 0, 0, 0.6) !important;
        cursor: pointer;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin-top: 2px !important;
        transition: opacity 0.2s !important;
    }
    .min-btn-wrapper button:hover {
        opacity: 0.8 !important;
    }

    .close-btn-wrapper button {
        border-radius: 50% !important;
        width: 18px !important;
        height: 18px !important;
        min-width: 18px !important;
        min-height: unset !important;
        padding: 0 !important;
        background-color: #ff5f56 !important; /* macOS red */
        border: none !important;
        font-size: 8px !important;
        font-weight: bold !important;
        color: rgba(0, 0, 0, 0.6) !important;
        cursor: pointer;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin-top: 2px !important;
        transition: opacity 0.2s !important;
    }
    .close-btn-wrapper button:hover {
        opacity: 0.8 !important;
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

# Render Website Layout (Always centered in background, no wide stretching)
st.markdown(f"<h1 style='font-size:2.4rem; font-weight:700; margin-bottom:0;'>🏢 {bot_info['name']}</h1>", unsafe_allow_html=True)
if bot_info['website_url']:
    st.caption(f"Official Portal: [{bot_info['website_url']}]({bot_info['website_url']})")
st.markdown("---")
st.write("Welcome to our simple web portal. Feel free to browse around or activate the support agent in the bottom right corner.")

# Render Chat Widget Window (As Floating Overlay)
if st.session_state.chat_open:
    with st.container(border=True):
        st.markdown('<div class="chat-widget-marker"></div>', unsafe_allow_html=True)
        
        # Widget Header Row (two columns: left for info, right for macOS controls)
        hdr_c1, hdr_c2 = st.columns([7, 3])
        with hdr_c1:
            st.html(
                f"""
                <div style='margin-top: 2px;'>
                    <div class='chat-header-title'>🤖 {bot_info['name']}</div>
                    <div class='chat-header-status'>● Online</div>
                </div>
                """
            )
        with hdr_c2:
            st.markdown('<div class="min-btn-wrapper">', unsafe_allow_html=True)
            if st.button("─", key="minimize_chat_widget", help="Minimize"):
                st.session_state.chat_open = False
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="close-btn-wrapper">', unsafe_allow_html=True)
            if st.button("✕", key="close_chat_session", help="Close Session"):
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
            
        st.html("<hr style='margin: 4px 0; border: 0; border-top: 1px solid rgba(128,128,128,0.15);'/>")
        
        # Scrollable chat logs container (increased height to 420px)
        chat_container = st.container(height=420)
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
            
            # Check if query is simple smalltalk, greeting, or acknowledgement
            clean_query = "".join(c for c in prompt.lower() if c.isalnum() or c.isspace()).strip()
            smalltalk_phrases = {
                "hi", "hello", "hey", "howdy", "greetings", "good morning", "good afternoon", "good evening", 
                "how are you", "hows it going", "how are you doing", "yo", "sup", "whats up",
                "thanks", "thank you", "thank you so much", "perfect", "ok", "okay", "awesome", "cool", "great"
            }
            is_smalltalk = clean_query in smalltalk_phrases
            
            if not is_smalltalk:
                with st.spinner("Searching..."):
                    try:
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

                        # Query Reformulation: Rephrase follow-up query to standalone query
                        standalone_query = prompt
                        if len(st.session_state.chat_history) > 1:
                            try:
                                # Load model settings to use current model for rephrasing
                                bot_settings = load_bot_settings(bot_id)
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
                                    except:
                                        pass

                                reformulate_model = genai.GenerativeModel(model_name=generation_model)
                                history_summary = ""
                                # Grab up to the last 5 turns of conversation context
                                recent_turns = st.session_state.chat_history[-5:-1]
                                for msg in recent_turns:
                                    role_name = "User" if msg["role"] == "user" else "Assistant"
                                    history_summary += f"{role_name}: {msg['content']}\n"
                                
                                reformulate_prompt = (
                                    "Given the following conversation history and a follow-up question, "
                                    "rephrase the follow-up question to be a standalone search query (do not answer the question, just rephrase it). "
                                    "If the question is already standalone, return it exactly as is.\n\n"
                                    f"Conversation History:\n{history_summary}\n"
                                    f"Follow-up Question: {prompt}\n"
                                    "Standalone Query:"
                                )
                                
                                rewrite_res = reformulate_model.generate_content(reformulate_prompt)
                                standalone_query = rewrite_res.text.strip()
                            except Exception as e:
                                standalone_query = prompt

                        emb_res = genai.embed_content(
                            model=embedding_model,
                            content=standalone_query,
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
                    f"[INSTRUCTION]\n"
                    f"You are a helpful customer support agent representing {bot_info['name']}.\n"
                    "- Your answers should be friendly, conversational, and direct.\n"
                    "- Base your answer ONLY on the provided Context. If the answer cannot be found in the context, "
                    "politely state that you do not have that information and suggest contacting human support.\n"
                    "- Do not make up facts.\n"
                    "- Output ONLY the final customer-facing response. Do NOT output any chain of thought, reasoning, "
                    "notes, drafts, evaluations, self-corrections, or internal planning.\n"
                    "[/INSTRUCTION]"
                )
                system_instruction = bot_settings.get("system_prompt")
                if not system_instruction:
                    system_instruction = default_system_prompt
                    
                generation_config = {
                    "temperature": float(bot_settings.get("temperature", 0.7)),
                    "top_p": float(bot_settings.get("top_p", 0.95)),
                    "max_output_tokens": int(bot_settings.get("max_output_tokens", 1024))
                }
                
                # Construct history string to provide full context to generation LLM
                history_str = ""
                recent_history = st.session_state.chat_history[-7:-1] if len(st.session_state.chat_history) > 1 else []
                for msg in recent_history:
                    role_name = "User" if msg["role"] == "user" else "Assistant"
                    history_str += f"{role_name}: {msg['content']}\n"
                    
                if is_smalltalk:
                    full_prompt = (
                        f"Respond politely and briefly to the user's greeting, smalltalk, or acknowledgement. "
                        "Do not make up facts or mention documentation. "
                        "Output ONLY the final response to the user. Do not include any internal thoughts, drafts, or reasoning.\n\n"
                        f"Previous Conversation:\n{history_str}\n"
                        f"User: {prompt}\n"
                        f"Answer: "
                    )
                elif context:
                    full_prompt = (
                        f"Context about {bot_info['name']}:\n{context}\n\n"
                        f"Previous Conversation:\n{history_str}\n"
                        f"User Question: {prompt}\n"
                        f"Answer: "
                    )
                else:
                    full_prompt = (
                        f"Note: No documents or website pages have been ingested for this bot yet. "
                        "Politely inform the user that you are still being configured and do not have access to any knowledge yet.\n"
                        f"Previous Conversation:\n{history_str}\n"
                        f"User Question: {prompt}\n"
                        f"Answer: "
                    )
                    
                # Determine provider
                provider = bot_settings.get("provider", "gemini")
                use_groq = (provider == "groq") or (groq_key and not gemini_key)
                
                try:
                    full_response = ""
                    if use_groq:
                        # Map default Groq model if the model doesn't match Groq names
                        groq_model = generation_model
                        if not any(kw in groq_model.lower() for kw in ["llama", "mixtral", "gemma"]):
                            groq_model = "llama-3.3-70b-versatile"
                            
                        import requests
                        headers = {
                            "Authorization": f"Bearer {groq_key}",
                            "Content-Type": "application/json"
                        }
                        
                        # Format messages payload
                        messages_payload = []
                        if is_smalltalk:
                            messages_payload.append({
                                "role": "system", 
                                "content": (
                                    "[INSTRUCTION]\n"
                                    "Respond politely and briefly to the user's greeting, smalltalk, or acknowledgement. "
                                    "Do not make up facts or mention documentation. "
                                    "Output ONLY the final response. Do NOT output any chain of thought, reasoning, notes, drafts, or self-corrections.\n"
                                    "[/INSTRUCTION]"
                                )
                            })
                        else:
                            sys_content = system_instruction if system_instruction else default_system_prompt
                            if context:
                                sys_content += f"\n\nContext information about {bot_info['name']}:\n{context}"
                            messages_payload.append({"role": "system", "content": sys_content})
                        
                        # Load recent history
                        recent_history = st.session_state.chat_history[-7:-1] if len(st.session_state.chat_history) > 1 else []
                        for msg in recent_history:
                            role_type = msg["role"]
                            messages_payload.append({"role": role_type, "content": msg["content"]})
                            
                        messages_payload.append({"role": "user", "content": prompt})
                        
                        payload = {
                            "model": groq_model,
                            "messages": messages_payload,
                            "temperature": float(bot_settings.get("temperature", 0.7)),
                            "max_tokens": int(bot_settings.get("max_output_tokens", 1024)),
                            "top_p": float(bot_settings.get("top_p", 0.95)),
                            "stream": True
                        }
                        
                        response = requests.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers=headers,
                            json=payload,
                            stream=True
                        )
                        
                        if response.status_code != 200:
                            raise Exception(f"Groq API returned status code {response.status_code}: {response.text}")
                        
                        # Stream parsing
                        for line in response.iter_lines():
                            if line:
                                decoded_line = line.decode('utf-8')
                                if decoded_line.startswith("data: "):
                                    data_str = decoded_line[6:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        data_json = json.loads(data_str)
                                        delta = data_json["choices"][0]["delta"].get("content", "")
                                        full_response += delta
                                        message_placeholder.markdown(
                                            f"<div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.15); padding: 10px 14px; border-radius: 14px; display: inline-block; max-width: 85%; line-height: 1.4;'>{full_response}▌</div>",
                                            unsafe_allow_html=True
                                        )
                                    except:
                                        pass
                        # Render final clean bubble
                        message_placeholder.markdown(
                            f"<div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.15); padding: 10px 14px; border-radius: 14px; display: inline-block; max-width: 85%; line-height: 1.4;'>{full_response}</div>",
                            unsafe_allow_html=True
                        )
                    else:
                        # Compile fallback list of models to try in case of 429 quota exceed
                        models_to_try = [generation_model]
                        try:
                            available_models = genai.list_models()
                            valid_gen_models = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
                            for m in ["models/gemini-2.5-flash", "models/gemini-2.5-pro"]:
                                if m in valid_gen_models and m not in models_to_try:
                                    models_to_try.append(m)
                            for vm in valid_gen_models:
                                if vm not in models_to_try:
                                    models_to_try.append(vm)
                        except:
                            pass
                            
                        for fallback_m in ["models/gemini-2.5-flash", "models/gemini-2.5-pro"]:
                            if fallback_m not in models_to_try:
                                models_to_try.append(fallback_m)
                                
                        success = False
                        errors = []
                        
                        for active_model_name in models_to_try:
                            try:
                                model = genai.GenerativeModel(
                                    model_name=active_model_name,
                                    system_instruction=system_instruction
                                )
                                
                                # Stream the response
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
                                
                                message_placeholder.markdown(
                                    f"<div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.15); padding: 10px 14px; border-radius: 14px; display: inline-block; max-width: 85%; line-height: 1.4;'>{full_response}</div>",
                                    unsafe_allow_html=True
                                )
                                success = True
                                break
                            except Exception as e:
                                errors.append((active_model_name, e))
                                # Continue loop to try the next model
                                continue
                                
                        if not success:
                            # Last resort: if Gemini fails but a Groq API key is provided, try Groq!
                            if groq_key:
                                try:
                                    st.info("ℹ️ Gemini quota limit reached. Safely falling back to Groq Llama model...")
                                    import requests
                                    headers = {
                                        "Authorization": f"Bearer {groq_key}",
                                        "Content-Type": "application/json"
                                    }
                                    
                                    # Format messages payload
                                    messages_payload = []
                                    if is_smalltalk:
                                        messages_payload.append({
                                            "role": "system", 
                                            "content": (
                                                "[INSTRUCTION]\n"
                                                "Respond politely and briefly to the user's greeting, smalltalk, or acknowledgement. "
                                                "Do not make up facts or mention documentation. "
                                                "Output ONLY the final response. Do NOT output any chain of thought, reasoning, notes, drafts, or self-corrections.\n"
                                                "[/INSTRUCTION]"
                                            )
                                        })
                                    else:
                                        sys_content = system_instruction if system_instruction else default_system_prompt
                                        if context:
                                            sys_content += f"\n\nContext information about {bot_info['name']}:\n{context}"
                                        messages_payload.append({"role": "system", "content": sys_content})
                                    
                                    # Load recent history
                                    recent_history = st.session_state.chat_history[-7:-1] if len(st.session_state.chat_history) > 1 else []
                                    for msg in recent_history:
                                        role_type = msg["role"]
                                        messages_payload.append({"role": role_type, "content": msg["content"]})
                                        
                                    messages_payload.append({"role": "user", "content": prompt})
                                    
                                    payload = {
                                        "model": "llama-3.3-70b-versatile",
                                        "messages": messages_payload,
                                        "temperature": float(bot_settings.get("temperature", 0.7)),
                                        "max_tokens": int(bot_settings.get("max_output_tokens", 1024)),
                                        "top_p": float(bot_settings.get("top_p", 0.95)),
                                        "stream": True
                                    }
                                    
                                    response = requests.post(
                                        "https://api.groq.com/openai/v1/chat/completions",
                                        headers=headers,
                                        json=payload,
                                        stream=True
                                    )
                                    
                                    if response.status_code == 200:
                                        # Stream parsing
                                        for line in response.iter_lines():
                                            if line:
                                                decoded_line = line.decode('utf-8')
                                                if decoded_line.startswith("data: "):
                                                    data_str = decoded_line[6:].strip()
                                                    if data_str == "[DONE]":
                                                        break
                                                    try:
                                                        data_json = json.loads(data_str)
                                                        delta = data_json["choices"][0]["delta"].get("content", "")
                                                        full_response += delta
                                                        message_placeholder.markdown(
                                                            f"<div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.15); padding: 10px 14px; border-radius: 14px; display: inline-block; max-width: 85%; line-height: 1.4;'>{full_response}▌</div>",
                                                            unsafe_allow_html=True
                                                        )
                                                    except:
                                                        pass
                                        message_placeholder.markdown(
                                            f"<div style='background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid rgba(128,128,128,0.15); padding: 10px 14px; border-radius: 14px; display: inline-block; max-width: 85%; line-height: 1.4;'>{full_response}</div>",
                                            unsafe_allow_html=True
                                        )
                                        success = True
                                except:
                                    pass
                                    
                        if not success:
                            # Find if any error was a 429 rate limit or quota exceed
                            quota_error = None
                            for m_name, err in errors:
                                err_msg = str(err)
                                if "429" in err_msg or "quota" in err_msg.lower():
                                    quota_error = err
                                    break
                            if quota_error:
                                raise quota_error
                            elif errors:
                                raise errors[0][1]
                            else:
                                raise Exception("All fallback generative models failed to respond.")
                    
                    # Show sources if RAG was active
                    if sources:
                        with st.expander("🔍 View Sources"):
                            for src_url, similarity in sources:
                                st.markdown(f"- **[Link]({src_url})** (Relevance: {similarity:.2f})")
                                
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

# Auto-scroll helper injection
if st.session_state.chat_open:
    st.html(
        """
        <iframe src="about:blank" style="display:none;" onload="
            setTimeout(() => {
                const widget = window.parent.document.querySelector('div[data-testid*=stVerticalBlockBorderWrapper]:has(.chat-widget-marker)');
                if (widget) {
                    const scrollable = widget.querySelector('div[style*=\\'overflow\\']');
                    if (scrollable) {
                        scrollable.scrollTop = scrollable.scrollHeight;
                    }
                }
            }, 50);
        "></iframe>
        """
    )
