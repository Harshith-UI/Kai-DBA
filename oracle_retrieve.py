import array
import logging
from db import get_connection
from utils import get_embeddings

logger=logging.getLogger(__name__)

def retrieve_oracle(question):
    conn = get_connection()
    cursor = conn.cursor()
    logger.info("Oracle DB connection opened for retrieval")
    try:
        embeddings = get_embeddings()
        logger.debug("Initialized embeddings model")
        logger.debug("Embedding query: %s", question)
        vector = embeddings.embed_query(question)
        logger.debug("Embedding generated: %s", vector)
        logger.debug("Querying Oracle DB for relevant documents")
        cursor.execute(
        """
        SELECT PARENT_ID,VECTOR_DISTANCE(VECTOR, :query_vector, COSINE) AS distance
        FROM TICKETS
        WHERE VECTOR IS NOT NULL
            AND VECTOR_DISTANCE(VECTOR, :query_vector, COSINE) < 0.4
        ORDER by distance
        """,
        [array.array('f', vector), array.array('f', vector)]
        )
        results = cursor.fetchall()
        logger.info("Vector search returned %d rows with vector distance less than 0.4", len(results))
        if not results:
            logger.warning("No relevant vector matches found for question")
            return {
                "context":"No relevant data found",
                "found":False
            }
        parent_ids = []
        vector_distances = []
        seen_parent_ids = set()
        for result in results:
            parent_id = result[0]
            if parent_id not in seen_parent_ids:
                parent_ids.append(parent_id)
                vector_distances.append(result[1])
                seen_parent_ids.add(parent_id)
        parent_contents = []
        for parent_id in parent_ids:
            logger.debug("Fetching parent content for parent_id=%s", parent_id)
            cursor.execute(
            """
            SELECT CONTENT
            FROM TICKETS
            WHERE ID = :parent_id
            """,
            [parent_id]
            )
            parent_result = cursor.fetchone()
            if parent_result:
                logger.debug("Parent content found for parent_id=%s", parent_id)
                parent_contents.append(parent_result[0].read())
            else:
                logger.warning("No parent content found for parent_id=%s", parent_id)
        if not parent_contents:
            logger.warning("No parent contents found after vector search")
            return "No parent content found"
        logger.info("Parent contents fetched: %d", len(parent_contents))
        print("Vector Distances :")
        for i, score in enumerate(vector_distances, start=1):
            print(f"  {i}. {score}")
        if len(parent_contents) == 1:
            logger.info("Returning single parent section as context")
            return parent_contents[0]
        formatted_sections = []
        for i, content in enumerate(parent_contents, start=1):
            formatted_sections.append(f"--- Parent Section {i} ---\n\n{content}")
        logger.info("Returning combined parent sections as context")
        return {"context":"\n\n".join(formatted_sections),
                "found":True}
    finally:
        conn.close()
        logger.info("Oracle DB connection closed after retrieval")

if __name__ == "__main__":
    print(retrieve_oracle("How to rollback tablespace extension?"))
