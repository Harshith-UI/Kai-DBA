from langchain_pinecone import PineconeVectorStore
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_openai import OpenAIEmbeddings,ChatOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

def get_vectorstore(indexname):
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=os.getenv("OPENAI_API_KEY")
    )
    return PineconeVectorStore(
        index_name=indexname,
        namespace='testing',
        embedding=embeddings
    )

def similarity_retrieve(indexname):
    retriever = get_vectorstore(indexname).as_retriever(
        search_type='similarity',
        search_kwargs={'k': 3}
    )
    return retriever

def mmr_retrieve(indexname):
    retriever = get_vectorstore(indexname).as_retriever(
        search_type='mmr',
        search_kwargs={'k': 3, 'fetch_k': 10, 'lambda_mult': 0.5}
    )
    return retriever

def multiqueryretrieve(indexname):
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=os.getenv("OPENAI_API_KEY")
    )
    retriever = get_vectorstore(indexname).as_retriever(
        search_type='similarity',
        search_kwargs={'k': 3}
    )
    multi_retriever = MultiQueryRetriever.from_llm(
        retriever=retriever,
        llm=llm
    )
    return multi_retriever
