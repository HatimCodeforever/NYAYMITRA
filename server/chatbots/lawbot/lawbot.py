import chainlit as cl
import requests
import sys 
import os
current_script_directory = os.path.dirname(os.path.abspath(__file__))
chatbots_directory = os.path.abspath(os.path.join(current_script_directory, '..'))
server_side_directory = os.path.abspath(os.path.join(chatbots_directory, '..'))
sys.path.append(server_side_directory)
from chatbots.utils import *
openai.api_key = os.environ.get("OPENAI_API_KEY")

# full_doc_retriever = get_parent_docs_retriever(PINECONE_INDEX_NAME, EMBEDDINGS, LOCAL_FILE_STORE_PATH, CHILD_SPLITTER)
vectordb = Pinecone.from_existing_index(PINECONE_INDEX_NAME, EMBEDDINGS, text_key='key')

@cl.on_chat_start
def start_chat():
    # chain = nyaymitra_kyr_chain(full_doc_retriever)
    chain = nyaymitra_kyr_chain_with_local_llm(vectordb)
    cl.user_session.set("chain", chain)

@cl.on_message
async def main(message: cl.Message):
    source_lang = detect_source_langauge(message.content)
    if source_lang != 'en':
        trans_query = GoogleTranslator(source=source_lang, target='en').translate(message.content)
    else:
        trans_query = message.content
    print('Translated Query', trans_query)

    await cl.Avatar(
        name="Tool 1",
        path="./public/logo_.png",
    ).send()
    chain = cl.user_session.get("chain")
    cb = cl.AsyncLangchainCallbackHandler()
    response = await chain.acall(trans_query, callbacks=[cb])
    final_answer = response.get('answer')
    source_documents = response.get('source_documents', [])
    source_pdfs = [source_document.metadata['source'] for source_document in source_documents]
    print('RESPONSE:', final_answer)
    print('SOURCE DOCUMENTS:',source_pdfs)
    if source_lang != 'en':
        trans_output = GoogleTranslator(source='auto', target=source_lang).translate(final_answer)
    else:
        trans_output = final_answer
    # Sql Database
    # data = {}
    # data['answer']=trans_output
    # data['query']=trans_query
    # response = requests.post('http://127.0.0.1:5000/category', json=data,headers = {"Content-Type": "application/json"})
    # if response.status_code == 200:
    #     print('Response from Flask server:', response.text)
    # else:
    #     print('Error occurred:', response.status_code)
  
    # # Simulate typing animation
    # for char in final_answer:
    #     await cl.Message(content=char).send()
    #     await asyncio.sleep(0.1)  # Adjust this value to change typing speed


    # source_documents = res["source_documents"]
    # text_elements = []
    # if source_documents:
    #     for source_idx, source_doc in enumerate(source_documents):
    #         source_name = f"source_{source_idx}"
    #         # Create the text element referenced in the message
    #         text_elements.append(
    #             cl.Text(content=source_doc.page_content, name=source_name)
    #         )
    #     source_names = [text_el.name for text_el in text_elements]

    #     if source_names:
    #         answer += f"\nSources: {', '.join(source_names)}"
    #     else:
    #         answer += "\nNo sources found"

    await cl.Message(content=trans_output,author="Tool 1").send()

