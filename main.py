from oracle_retrieve import retrieve_oracle
from oracle_chain import get_oracle_answer
import requests,os
from dotenv import load_dotenv
load_dotenv()
if __name__ == "__main__":
    question = "rollback tablespace extension"
    url=os.getenv("REDACT_URL")
    key=os.getenv("REDACT_KEY")
    headers={"REDACT_KEY": key}
    data={"question":question}
    retrieved_data = retrieve_oracle(question)
    if retrieved_data["found"]:
        context = retrieved_data["context"]
        answer = get_oracle_answer(question, context)
        print(answer)
    else:
        response=requests.post(url,json=data,headers=headers)
        print(response.text)