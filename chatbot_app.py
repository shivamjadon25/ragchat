import streamlit as st
import google.generativeai as genai
import os
import json
from urllib.parse import urlparse
from supabase import create_client, Client

# Set page configuration
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

# ----------------- DISPLAY CHAT HEADER -----------------
col_title, col_reset = st.columns([8, 2])
with col_title:
    st.title(f"💬 {bot_info['name']}")
    if bot_info['website_url']:
        st.caption(f"Support agent for: [{bot_info['website_url']}]({bot_info['website_url']})")
    else:
        st.caption("Custom Support Agent")
with col_reset:
    st.write("") # alignment spacing
    if st.button("🔄 Reset Chat", use_container_width=True, help="Clear history and start a new conversation session"):
        st.session_state.chat_history = []
        st.session_state.conversation_id = None
        st.rerun()

st.markdown("---")

# Show chat history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            st.markdown("<div style='display:flex; flex-wrap:wrap; gap:8px; margin-top:8px;'>", unsafe_allow_html=True)
            for src_url, similarity in msg["sources"]:
                domain = urlparse(src_url).netloc or "Source Link"
                st.markdown(
                    f"<a href='{src_url}' target='_blank' style='text-decoration:none; color:var(--text-color); background-color:var(--secondary-background-color); border:1px solid rgba(128,128,128,0.25); padding:4px 10px; border-radius:16px; font-size:0.8rem; display:inline-flex; align-items:center; gap:4px;'>"
                    f"🔗 {domain} <span style='opacity:0.6;'>({similarity:.2f})</span>"
                    f"</a>",
                    unsafe_allow_html=True
                )
            st.markdown("</div>", unsafe_allow_html=True)

# ----------------- PROMPT AND LOGIC RESOLUTION -----------------
prompt = None

# If chat history is empty, show starter suggestions
if not st.session_state.chat_history:
    st.markdown("<p style='text-align:center; opacity:0.8; font-size:1.1rem; margin-top:2rem;'>Hello! How can I assist you today?</p>", unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:1.5rem;'></div>", unsafe_allow_html=True)
    
    col_s1, col_s2 = st.columns(2)
    starters = [
        f"What services does {bot_info['name']} offer?",
        f"How can I contact support representatives?",
        f"Can you summarize the main features?",
        f"Where can I find additional documentation?"
    ]
    
    with col_s1:
        if st.button(starters[0], key="starter_0", use_container_width=True):
            st.session_state.selected_prompt = starters[0]
            st.rerun()
        if st.button(starters[1], key="starter_1", use_container_width=True):
            st.session_state.selected_prompt = starters[1]
            st.rerun()
    with col_s2:
        if st.button(starters[2], key="starter_2", use_container_width=True):
            st.session_state.selected_prompt = starters[2]
            st.rerun()
        if st.button(starters[3], key="starter_3", use_container_width=True):
            st.session_state.selected_prompt = starters[3]
            st.rerun()

# Check click selections
if "selected_prompt" in st.session_state and st.session_state.selected_prompt:
    prompt = st.session_state.selected_prompt
    st.session_state.selected_prompt = None
else:
    prompt_input = st.chat_input("Ask a question...")
    if prompt_input:
        prompt = prompt_input

if prompt:
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    
    # Save User message to Database
    try:
        supabase.table("messages").insert({
            "conversation_id": st.session_state.conversation_id,
            "role": "user",
            "content": prompt
        }).execute()
    except Exception as e:
        st.warning(f"Failed to log user message to database: {e}")

    # 1. RAG Search (Retrieve matching content from Supabase vector index)
    context = ""
    sources = []
    
    with st.spinner("Searching knowledge base..."):
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
            
            # Stream the response
            full_response = ""
            response_stream = model.generate_content(
                full_prompt, 
                generation_config=generation_config,
                stream=True
            )
            for chunk in response_stream:
                full_response += chunk.text
                message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.markdown(full_response)
            
            # Show sources if RAG was active
            if sources:
                st.markdown("<div style='display:flex; flex-wrap:wrap; gap:8px; margin-top:8px;'>", unsafe_allow_html=True)
                for src_url, similarity in sources:
                    domain = urlparse(src_url).netloc or "Source Link"
                    st.markdown(
                        f"<a href='{src_url}' target='_blank' style='text-decoration:none; color:var(--text-color); background-color:var(--secondary-background-color); border:1px solid rgba(128,128,128,0.25); padding:4px 10px; border-radius:16px; font-size:0.8rem; display:inline-flex; align-items:center; gap:4px;'>"
                        f"🔗 {domain} <span style='opacity:0.6;'>({similarity:.2f})</span>"
                        f"</a>",
                        unsafe_allow_html=True
                    )
                st.markdown("</div>", unsafe_allow_html=True)
                        
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
            
        except Exception as e:
            st.error(f"Error generating response: {e}")
