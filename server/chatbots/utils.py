import os
from dotenv import load_dotenv

import torch

from langchain.llms import OpenAI
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, PromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain.retrievers import ParentDocumentRetriever
from langchain.document_loaders import PyPDFLoader, DirectoryLoader, UnstructuredFileLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceBgeEmbeddings
from langchain.vectorstores import Pinecone, FAISS
from langchain.memory import ConversationBufferWindowMemory
from langchain.chains import LLMChain, RetrievalQA, ConversationalRetrievalChain
from langchain.storage import LocalFileStore
from langchain.storage._lc_store import create_kv_docstore
import openai
import pinecone
from lingua import Language, LanguageDetectorBuilder
import iso639
from deep_translator import GoogleTranslator
import os
import nltk

current_script_directory = os.path.dirname(os.path.abspath(__file__))

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY_FOR_LAWBOT")
PINECONE_ENV = os.getenv("PINECONE_ENV")
PINECONE_INDEX_NAME = 'nyaymitra'
LOCAL_FILE_STORE_PATH = os.path.abspath(os.path.join(current_script_directory, os.pardir, 'local_file_store'))    
CHILD_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=400)        # Splitter For Advanced RAG
DATA_DIRECTORY = os.path.abspath(os.path.join(current_script_directory, os.pardir, 'nyaymitra_data'))      # Directory Consisting Data For Nyaymitra
NEW_DATA_DIRECTORY = ''

# Will store the pdfs entered by the user:
USER_DIRECTORY_FOR_DOC_QNA = '../document_sum/user_data'

# file path to store the embeddings in faiss vectore store:
FAISS_INDEX_FILE_PATH = '../document_sum/faiss_index'

# Detector For Language Detection
DETECTOR = LanguageDetectorBuilder.from_all_languages().with_preloaded_language_models().build()

DEVICE_TYPE = 'cuda' if torch.cuda.is_available() else 'cpu'

# Loading BGE Embeddings From HuggingFace
EMBEDDING_MODEL_NAME = "BAAI/bge-large-en-v1.5"
EMBEDDINGS = HuggingFaceBgeEmbeddings(
    model_name= EMBEDDING_MODEL_NAME,
    model_kwargs={'device': DEVICE_TYPE},
    encode_kwargs={'normalize_embeddings': True}# Set True to compute cosine similarity
)

# Initialize Pinecone
pinecone.init(
    api_key= PINECONE_API_KEY,  
    environment= PINECONE_ENV,  
)

# Download Punkt Package
nltk.download('punkt')



# FUNCTION FOR CREATING INTIAL PINECONE INDEX FROM DIRECTORY
def load_data_to_pinecone_vectorstore(data_directory, index_name, embeddings):
    loader = DirectoryLoader(data_directory, glob="*.pdf", loader_cls=PyPDFLoader)
    data = loader.load()

    text_splitter  = RecursiveCharacterTextSplitter(chunk_size=1000,chunk_overlap=200)
    docs = text_splitter.split_documents(data)

    if index_name in pinecone.list_indexes():
      pinecone.delete_index(index_name)

    pinecone.create_index(name=index_name, dimension=1024, metric="cosine")

    vectordb = Pinecone.from_documents(documents = docs,index_name = index_name, embedding =embeddings)

    return vectordb

# vectordb = load_data_to_pinecone_vectorstore(DATA_DIRECTORY, PINECONE_INDEX_NAME, EMBEDDINGS)

def add_data_to_pinecone_vectorstore(data_directory, index_name, embeddings):
    loader = DirectoryLoader(data_directory, glob="*.pdf", loader_cls=PyPDFLoader)
    data = loader.load()

    text_splitter  = RecursiveCharacterTextSplitter(chunk_size=1000,chunk_overlap=200)
    docs = text_splitter.split_documents(data)

    index = pinecone.Index(index_name)
    vectorstore = Pinecone(
      index = index,
      embedding = embeddings,
      text_key = 'key'
    )

    vectorstore.add_documents(docs)

    return vectorstore

# vectordb = add_data_to_pinecone_vectorstore(NEW_DATA_DIRECTORY, PINECONE_INDEX_NAME, EMBEDDINGS)

def nyaymitra_kyr_chain(vectordb):
    llm = ChatOpenAI(model_name="gpt-3.5-turbo-1106",streaming=True ,temperature=0.0,max_tokens=1000)
    system_message_prompt = SystemMessagePromptTemplate.from_template(
       """You are a law expert in India, and your role is to assist users in understanding their rights based on queries related to the provided legal context from Indian documents. Utilize the context to offer detailed responses, citing the most relevant laws and articles. If a law or article isn't pertinent to the query, exclude it. Recognize that users may not comprehend legal jargon, so after stating the legal terms, provide simplified explanations for better user understanding.
        Important Instructions:
        1. Context and Precision: Tailor your response to the user's query using the specific details provided in the legal context from India. Use only the most relevant laws and articles from the context.
        2. Comprehensive and Simplified Responses: Offer thorough responses by incorporating all relevant laws and articles. For each legal term, provide a user-friendly explanation to enhance comprehension.
        3. User-Friendly Language: Aim for simplicity in your explanations, considering that users may not have a legal background. Break down complex terms or phrases to make them more accessible to the user. Provide examples on how the law is relevant and useful to the user's query.
        LEGAL CONTEXT: \n{context}"""
    )
    human_message_prompt = HumanMessagePromptTemplate.from_template("{question}")
    
    prompt_template = ChatPromptTemplate.from_messages([
            system_message_prompt,
            human_message_prompt,
        ])  
    
    retriever = vectordb.as_retriever()
    memory = ConversationBufferWindowMemory(k=15, memory_key="chat_history", return_messages=True)

    chain = ConversationalRetrievalChain.from_llm(
      llm=llm,
      retriever=retriever,
      memory=memory,
      combine_docs_chain_kwargs={"prompt": prompt_template}
    )
    return chain

# vectordb = Pinecone.from_existing_index(index_name= PINECONE_INDEX_NAME, embedding=EMBEDDINGS)

def detect_source_langauge(text):
    detected_language = str(DETECTOR.detect_language_of(text)).split('.')[1].title()
    print('Detected Language', detected_language)
    source_language = iso639.Language.from_name(detected_language).part1
    
    return source_language

def create_faiss_vectordb_for_document_qna(user_data_directory,embeddings):
  loader = DirectoryLoader(user_data_directory, loader_cls=UnstructuredFileLoader)
  docs = loader.load()
  doc_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
  split_docs = doc_splitter.split_documents(docs)
  texts = [doc.page_content for doc in split_docs]
  print(texts)
  source_language = detect_source_langauge(texts[0])
  if source_language != 'en':
     trans_texts = GoogleTranslator(source=source_language, target='en').translate_batch(texts)
  else:
     trans_texts = texts
  
  print('CREATING EMBEDDINGS FOR USER DOCUMENT')
  vectordb = FAISS.from_texts(trans_texts, embedding=embeddings)
  print('FAISS VECTOR DATABASE CREATED')
  vectordb.save_local(FAISS_INDEX_FILE_PATH)

  return vectordb

# ------------------------------------------------------ FULL DOCS RETRIEVER -----------------------------------------------
 
# FUNCTION TO CREATE VECTOR DATABASE WITH PARENTS DOCS RETRIEVER
def load_data_to_pinecone_vectorstore(data_directory, index_name, embeddings, local_file_store_path, child_splitter):
    """
    Function to create embeddings for Pinecone database and creating a Parent Document Retriever using a local docstore.
    Returns: vectorstore: instance of the pinecone vector database
             store: The instance of LocalFileStore that contains the index which maps the Parent Document to the child document.
    """
    loader = DirectoryLoader(data_directory, glob="*.pdf", loader_cls=PyPDFLoader)
    data = loader.load()

    text_splitter  = RecursiveCharacterTextSplitter(chunk_size=1000,chunk_overlap=200)
    docs = text_splitter.split_documents(data)

    if index_name in pinecone.list_indexes():
      pinecone.delete_index(index_name)

    pinecone.create_index(name=index_name, dimension=1024, metric="cosine")

    index = pinecone.Index(index_name)
    vectorstore = Pinecone(
      index = index,
      embedding = embeddings,
      text_key = 'key'
    )

    file_store = LocalFileStore(local_file_store_path)
    store = create_kv_docstore(file_store)

    full_doc_retriever = ParentDocumentRetriever(
      vectorstore=vectorstore,
      docstore=store,
      child_splitter=child_splitter,
    )

    print('Creating Embeddings')
    full_doc_retriever.add_documents(docs, ids=None)
    print("Vector Database Created")

    return vectorstore, store

# vectorstore, store = load_data_to_pinecone_vectorstore(DATA_DIRECTORY, INDEX_NAME, EMBEDDINGS, LOCAL_FILE_STORE_PATH, CHILD_SPLITTER)

def get_parent_docs_retriever(index_name, embeddings, local_file_store_path, child_splitter):
  index = pinecone.Index(index_name)
  vectorstore = Pinecone(
    index = index,
    embedding = embeddings,
    text_key = 'key'
  )

  file_store = LocalFileStore(local_file_store_path)
  store = create_kv_docstore(file_store)

  full_doc_retriever = ParentDocumentRetriever(
    vectorstore=vectorstore,
    docstore=store,
    child_splitter=child_splitter,
  )

  return full_doc_retriever

# CHAIN WITH PARENTS DOCS RETRIEVER
def nyaymitra_kyr_chain(full_doc_retriever):
    llm = ChatOpenAI(model_name="gpt-3.5-turbo-1106",streaming=True ,temperature=0.0,max_tokens=1000)
    # system_message_prompt = SystemMessagePromptTemplate.from_template(
    # "I want you to act as a law agent, understanding all laws and related jargon, and explaining them in a simpler and descriptive way. Return a list of all the related LAWS drafted and provided in the Context for the user_input question and provide proper penal codes if applicable from the ingested PDF, and explain the process and terms in a simpler way. Dont go beyond the context of the pdf please be precise and accurate. The context is:\n{context}"
    # )
    # system_message_prompt = SystemMessagePromptTemplate.from_template(
    #    "You are a law expert in India, and your task is to help users know their rights given a query. You will be provided with context from legal documents from India that you are supposed to use to respond to the user's queries. The user might not understand legal jargon. So, after stating the legal jargon, simplify them for better understanding of the user. Use all the relevant laws from the context based on the user's query. Only include the most relevant laws and articles from the context based on the user query. Do not use any law or article from the context if it's not relevant to the query. The context is: \n{context}"
    # )
    system_message_prompt = SystemMessagePromptTemplate.from_template(
       """You are a law expert in India, and your role is to assist users in understanding their rights based on queries related to the provided legal context from Indian documents. Utilize the context to offer detailed responses, citing the most relevant laws and articles. If a law or article isn't pertinent to the query, exclude it. Recognize that users may not comprehend legal jargon, so after stating the legal terms, provide simplified explanations for better user understanding.
        Important Instructions:
        1. Context and Precision: Tailor your response to the user's query using the specific details provided in the legal context from India. Use only the most relevant laws and articles from the context.
        2. Comprehensive and Simplified Responses: Offer thorough responses by incorporating all relevant laws and articles. For each legal term, provide a user-friendly explanation to enhance comprehension.
        3. User-Friendly Language: Aim for simplicity in your explanations, considering that users may not have a legal background. Break down complex terms or phrases to make them more accessible to the user. Provide examples on how the law is relevant and useful to the user's query.
        LEGAL CONTEXT: \n{context}"""
    )
    human_message_prompt = HumanMessagePromptTemplate.from_template("{question}")
    
    prompt_template = ChatPromptTemplate.from_messages([
            system_message_prompt,
            human_message_prompt,
        ])  

    memory = ConversationBufferWindowMemory(k=15, memory_key="chat_history", return_messages=True)

    chain = ConversationalRetrievalChain.from_llm(
      llm=llm,
      retriever=full_doc_retriever,
      # input_key="query",
      # return_source_documents=True,
      memory=memory,
      combine_docs_chain_kwargs={"prompt": prompt_template}
    )
    return chain