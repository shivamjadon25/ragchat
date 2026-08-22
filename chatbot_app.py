import streamlit as st
import google.generativeai as genai
import os
import json
import time
from urllib.parse import urlparse
from supabase import create_client, Client

# Set page configuration to standard centered layout
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

# ----------------- DISPLAY CHAT -----------------
st.title(f"💬 Chat with {bot_info['name']}")
if bot_info['website_url']:
    st.caption(f"Support agent for: [{bot_info['website_url']}]({bot_info['website_url']})")
else:
    st.caption("Custom Support Agent")

# Show chat history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            with st.expander("🔍 View Sources"):
                for src_url, similarity in msg["sources"]:
                    st.markdown(f"- **[Link]({src_url})** (Relevance: {similarity:.2f})")

# User Input
if prompt := st.chat_input("Ask a question..."):
    # Refresh last activity time
    st.session_state.last_activity = time.time()
    
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
        pass
        
    # Check for goodbye
    clean_prompt = "".join(c for c in prompt.lower() if c.isalnum() or c.isspace()).strip()
    if clean_prompt in ["bye", "goodbye", "exit", "quit", "bye bye"]:
        farewell = f"Goodbye! Thank you for contacting {bot_info['name']} support. Starting a new chat session..."
        with st.chat_message("assistant"):
            st.markdown(farewell)
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
        st.session_state.last_activity = time.time()
        st.rerun()

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
        
        # Construct history string to provide full context to generation LLM
        history_str = ""
        recent_history = st.session_state.chat_history[-7:-1] if len(st.session_state.chat_history) > 1 else []
        for msg in recent_history:
            role_name = "User" if msg["role"] == "user" else "Assistant"
            history_str += f"{role_name}: {msg['content']}\n"
            
        if context:
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
