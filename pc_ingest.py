import os
from pinecone import Pinecone,ServerlessSpec    
from dotenv import load_dotenv
from utils import chunk_data,get_embeddings,load_data
load_dotenv()
def insert_pinecone(filename,indexname):  
    content=load_data(filename)
    chunks=chunk_data(content)
    embeddings=get_embeddings()
    pc=Pinecone(
        api_key=os.getenv('PINECONE_API_KEY')
    )
    if indexname not in pc.list_indexes().names():
        pc.create_index(
            name=indexname,
            dimension=1536,
            metric='cosine',
            spec=ServerlessSpec(
                cloud='aws',
                region='us-east-1'
            )
        )
    records=[]
    for i,chunk in enumerate(chunks):
        records.append(
            {
                'id':f'chunk-{i+1}',
                'values':embeddings.embed_query(chunk.page_content),
                'metadata': {
                    'text':chunk.page_content
}
            }
        )
    index=pc.Index(indexname)
    index.upsert(namespace='testing',vectors=records)
    print("Data ingested successfully")