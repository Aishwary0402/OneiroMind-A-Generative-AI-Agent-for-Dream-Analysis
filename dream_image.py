import os
import sys
import certifi
import time
import io
import requests
import base64
from PIL import Image
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

# --- Global Variables for AI components ---
llm = None
interpretation_chain = None
therapy_chain = None
visual_prompt_chain = None
stability_api_key = None # To be loaded at startup

def setup_ssl_certs(use_college_cert=False):
    """
    Silently configures SSL certificate paths for different network environments.
    """
    try:
        if use_college_cert:
            cert_path = "/Users/aishwarysinghrathour/Downloads/SSL_CA_YPR.pem" # Use your specific path if needed
        else:
            cert_path = certifi.where()

        if not os.path.exists(cert_path): return False

        os.environ['SSL_CERT_FILE'] = cert_path
        os.environ['REQUESTS_CA_BUNDLE'] = cert_path
        return True
    except Exception:
        return False

def get_api_keys():
    """
    Returns the hardcoded API keys.
    """
    # IMPORTANT: In a real application, use environment variables for keys.
    google_api_key = "AIzaSyAMEA-RmBeWWVvGtJnq__y4tHmciET9Ew0"
    global stability_api_key
    stability_api_key = "sk-DUJNE6Rj9N42qgMmu8udVqvY3xDApnQ0WDFhfaNVwaFepUaa"
    
    if not google_api_key or not stability_api_key:
        print("API Key is missing from the script. Exiting.")
        sys.exit(1)
    return google_api_key, stability_api_key

def setup_llm(google_api_key):
    """
    Initializes and returns the Language Model, handling potential SSL errors.
    """
    local_llm = None
    try:
        setup_ssl_certs(use_college_cert=False)
        local_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0.7, google_api_key=google_api_key, transport="rest")
        local_llm.invoke("test") 
    except Exception as e:
        if "SSL" in str(e) or "CERTIFICATE_VERIFY_FAILED" in str(e):
            print("\n⚠️ Network connection failed. Retrying with alternate configuration...")
            setup_ssl_certs(use_college_cert=True)
            try:
                local_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0.7, google_api_key=google_api_key, transport="rest")
                local_llm.invoke("test")
            except Exception as final_e:
                print(f"\n🚨 Critical Error: Connection failed. Error: {final_e}")
                sys.exit(1)
        else:
            print(f"\n🚨 An unexpected error occurred during LLM initialization: {e}")
            sys.exit(1)
    return local_llm

def load_or_create_knowledge_base(file_path, index_path, api_key):
    """
    Loads or creates the FAISS knowledge base.
    """
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=api_key, transport="rest")
    if os.path.exists(index_path):
        vector_store = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
        return vector_store.as_retriever(search_kwargs={"k": 5})
    
    print(f"\nCreating new knowledge base from '{file_path}'...")
    loader = TextLoader(file_path, encoding='utf-8')
    documents = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    splits = text_splitter.split_documents(documents)
    
    vector_store = FAISS.from_documents(splits, embeddings)
    vector_store.save_local(index_path)
    print("✅ Knowledge base created and saved.")
    return vector_store.as_retriever(search_kwargs={"k": 5})

def generate_dream_image_data(text_prompt):
    """
    Generates an image using Stability AI and returns it as a base64 data URI.
    """
    global stability_api_key
    if not stability_api_key:
        print("Error: Stability AI API key not found.")
        return None

    url = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {stability_api_key}"}
    payload = {"text_prompts": [{"text": text_prompt}], "cfg_scale": 7, "height": 1024, "width": 1024, "samples": 1, "steps": 30}

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"🚨 Error from Stability AI: {response.text}")
            return None
        data = response.json()
        image = data["artifacts"][0]
        base64_image = image["base64"]
        return f"data:image/png;base64,{base64_image}"
    except Exception as e:
        print(f"\nAn error occurred during image generation: {e}")
        return None

# MODIFIED FUNCTION
def create_chains(llm_instance, knowledge_base_retriever):
    """Creates all necessary LangChain chains for the application."""
    
    # MODIFIED Interpretation prompt to include demographics
    interpret_prompt = ChatPromptTemplate.from_template(
        """You are a dream interpreter. You provide two distinct interpretations for the dream below, based on general dream psychology and the user's specific demographic background. The user's demographics will provide crucial context for a more personalized and culturally relevant analysis.

        **User Demographics:** {demographics}

        Use this demographic information to tailor your interpretation. For example, a student's dream about failing might relate to academic pressure, while the same dream for a retired person could symbolize different anxieties.

        **CRUCIAL RULE:** Under no circumstances should you ever mention the dream dictionary, the provided context, or whether the context was sufficient or not. Your response must appear to come solely from your own expertise.

        Structure your response with these exact headings:
        **Direct Meaning:**
        **Symbolic Meaning:**
        **Combined Interpretation:**

        ---
        Dream: {dream_text}
        Context: {context}
        """
    )
    
    # MODIFIED Interpretation chain to accept a dictionary with dream_text and demographics
    interpretation_chain = (
        {
            "context": lambda x: knowledge_base_retriever.invoke(x["dream_text"]),
            "dream_text": lambda x: x["dream_text"],
            "demographics": lambda x: x["demographics"]
        }
        | interpret_prompt
        | llm_instance
        | StrOutputParser()
    )

    # Therapy Chain (remains the same)
    therapy_prompt = ChatPromptTemplate.from_template(
        """You are a supportive, conversational dream therapist. Your goal is to help the user explore their feelings about their dream interpretation. Ask open-ended questions to guide them.

        **CRUCIAL RULE:** If the user indicates they are satisfied, says "thank you," or expresses a desire to end the conversation (e.g., "no i am satisfied thank you again"), you MUST respect their decision. Do not challenge their feelings or push them to continue. Your response should be a polite and concise closing statement.

        **Correct Way to End:**
        User: "no i am satisfied thank you again"
        Your Response: "You're very welcome. I'm glad I could help. Feel free to return anytime you have another dream you'd like to discuss."

        **Incorrect Way to End:**
        User: "no i am satisfied thank you again"
        Your Response: "Okay, I hear you say you're satisfied, but sometimes..."

        ---
        Conversation History:
        {history}
        
        User's New Question/Statement:
        {question}
        
        Relevant Book Context:
        {context}
        
        Your helpful and respectful response:
        """
    )
    therapy_chain = (
        {"context": lambda x: knowledge_base_retriever.invoke(x["question"]), "question": lambda x: x["question"], "history": lambda x: x["history"]}
        | therapy_prompt | llm_instance | StrOutputParser()
    )
    
    # Visual Prompt Chain (remains the same)
    visual_prompt_template = ChatPromptTemplate.from_template(
        "Distill this dream interpretation into a concise, visually descriptive prompt for an AI image generator, focusing on concrete nouns, vivid adjectives, and mood as a comma-separated list: {interpretation}"
    )
    visual_prompt_chain = visual_prompt_template | llm_instance | StrOutputParser()
    
    return interpretation_chain, therapy_chain, visual_prompt_chain