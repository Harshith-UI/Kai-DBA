import array
import logging
from utils import get_embeddings,parent_child,load_data
from db import get_connection
from dotenv import load_dotenv
load_dotenv()
logger=logging.getLogger(__name__)

def ingest_oracle(filename):
    logger.info("Starting Oracle ingestion for file: %s", filename)
    content=load_data(filename)
    logger.info("Loaded source file successfully: %s", filename)
    parent_chunks, child_chunks = parent_child(content, source_name=filename)
    logger.info(
        "Prepared chunks for ingestion: parents=%d children=%d",
        len(parent_chunks),
        len(child_chunks)
    )
    if not parent_chunks:
        logger.warning("No parent chunks created for file: %s", filename)
    if not child_chunks:
        logger.warning("No child chunks created for file: %s", filename)
    embeddings=get_embeddings()
    logger.debug("Initialized embeddings model")
    conn=get_connection()
    logger.info("Oracle DB connection opened for ingestion")
    cursor=conn.cursor()
    for parent in parent_chunks:
        cursor.execute(
        """
        MERGE INTO TICKETS t
        USING (
            SELECT :1 AS ID, :2 AS PARENT_ID, :3 AS SECTION, :4 AS SUBSECTION, :5 AS CONTENT
            FROM dual
        ) src
        ON (t.ID = src.ID)
        WHEN MATCHED THEN UPDATE SET
            t.PARENT_ID = src.PARENT_ID,
            t.SECTION = src.SECTION,
            t.SUBSECTION = src.SUBSECTION,
            t.CONTENT = src.CONTENT,
            t.VECTOR = NULL
        WHEN NOT MATCHED THEN INSERT
            (ID, PARENT_ID, SECTION, SUBSECTION, CONTENT, VECTOR)
            VALUES (src.ID, src.PARENT_ID, src.SECTION, src.SUBSECTION, src.CONTENT, NULL)
        """,
        [
            parent["id"],    
            None,            
            parent["section"],
            None,
            parent["content"]
        ])
    logger.info("Finished upserting parent chunks: count=%d", len(parent_chunks))
    for child in child_chunks:
        logger.debug(
            "Generating embedding for child chunk: id=%s parent_id=%s section=%s subsection=%s",
            child["id"],
            child["parent_id"],
            child["section"],
            child["subsection"]
        )
        vector = embeddings.embed_documents([child["content"]])[0]
        vector = array.array('f', vector)
        logger.debug("Upserting child chunk: id=%s", child["id"])
        cursor.execute(
        """
        MERGE INTO TICKETS t
        USING (
            SELECT :1 AS ID, :2 AS PARENT_ID, :3 AS SECTION, :4 AS SUBSECTION, :5 AS CONTENT, :6 AS VECTOR
            FROM dual
        ) src
        ON (t.ID = src.ID)
        WHEN MATCHED THEN UPDATE SET
            t.PARENT_ID = src.PARENT_ID,
            t.SECTION = src.SECTION,
            t.SUBSECTION = src.SUBSECTION,
            t.CONTENT = src.CONTENT,
            t.VECTOR = src.VECTOR
        WHEN NOT MATCHED THEN INSERT
            (ID, PARENT_ID, SECTION, SUBSECTION, CONTENT, VECTOR)
            VALUES (src.ID, src.PARENT_ID, src.SECTION, src.SUBSECTION, src.CONTENT, src.VECTOR)
        """,
        [
            child["id"],
            child["parent_id"],
            child["section"],
            child["subsection"],
            child["content"],
            vector
        ])
    logger.info("Finished upserting child chunks: count=%d", len(child_chunks))
    conn.commit()
    logger.info("Committed changes and closed Oracle DB connection")
    conn.close()
    logger.info("Oracle ingestion completed successfully for file: %s", filename)

if __name__ == "__main__":
    ingest_oracle("sizeextension.md")
    
