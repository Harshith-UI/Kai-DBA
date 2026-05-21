import os
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter,MarkdownHeaderTextSplitter
from langchain_community.document_loaders import PyPDFLoader,TextLoader,CSVLoader
from langchain_openai import OpenAIEmbeddings
import uuid
load_dotenv()


def stable_chunk_id(*parts):
    key = "::".join("" if part is None else str(part) for part in parts)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def load_data(filename):
    if filename.endswith(".pdf"):
        loader=PyPDFLoader(filename)
    elif filename.endswith(".txt") or filename.endswith(".md"):
        loader=TextLoader(filename)
    elif filename.endswith(".csv"):
        loader=CSVLoader(filename)
    else:
        raise Exception('Unsupported file type')
    return loader.load()
def chunk_data(data):
    text_splitter=RecursiveCharacterTextSplitter(
        chunk_size=2000,
        chunk_overlap=200,

    )
    return text_splitter.split_documents(data)
def get_embeddings():
    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=os.getenv("OPENAI_API_KEY")
    )

def parent_child(data, source_name=""):
    parent_chunks = []
    child_chunks = []
    # parent splitter (only ##)
    parent_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("##", "section"),
        ]
    )
    # child splitter (## + ###)
    child_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("##", "section"),
            ("###", "subsection"),
        ]
    )
    for doc in data:
        text = doc.page_content
        # Parent chunks
        parents = parent_splitter.split_text(text)
        section_parent_map = {}
        for p in parents:
            section = p.metadata.get("section")
            parent_id = stable_chunk_id(source_name, "parent", section)
            section_parent_map[section] = parent_id
            parent_chunks.append({
                "id": parent_id,
                "section": section,
                "content": p.page_content
            })
        # Child chunks 
        children = child_splitter.split_text(text)
        for c in children:
            section = c.metadata.get("section")
            subsection = c.metadata.get("subsection")
            parent_id = section_parent_map.get(section)
            if parent_id:
                child_chunks.append({
                    "id": stable_chunk_id(source_name, "child", section, subsection, c.page_content),
                    "parent_id": parent_id,
                    "section": section,
                    "subsection": subsection,
                    "content": c.page_content
                })
    return parent_chunks, child_chunks
