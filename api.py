from fastapi import FastAPI
from pydantic import BaseModel
from oracle_retrieve import retrieve_oracle
from oracle_chain import get_oracle_answer
app=FastAPI()

@app.get("/")
def home():
    return {"message":"Welcome to Kai"}
class question(BaseModel):
    question:str
@app.post("/ask")
def ask(request:question):
    context=retrieve_oracle(request.question)
    answer = get_oracle_answer(request.question, context)
    return {"answer": answer}
