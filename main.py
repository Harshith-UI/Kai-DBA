from oracle_retrieve import retrieve_oracle
from oracle_chain import get_oracle_answer
import requests

if __name__ == "__main__":
    question = "Customer ACME account 883921 failing in PRODDB01. ORA-00001 unique constraint violated."
    url="https://n8n.manifestingpodcasts.site/webhook/sanitize"
    data={"question":question}
    retrieved_data = retrieve_oracle(question)
    if retrieved_data["found"]:
        context = retrieved_data["context"]
        answer = get_oracle_answer(question, context)
        print(answer)
    else:
        response=requests.post(url,data=data)
        print(response.text)