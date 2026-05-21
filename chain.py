from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

load_dotenv()
system_prompt = """You are an expert database support assistant for a database operations team.

You will be given a set of chunks retrieved from past resolved support tickets. These chunks may not all be relevant to the question — ignore any chunk that is not related to the question asked. The relevant information may also be spread across multiple chunks, so combine them if needed.

Based on the relevant chunks, provide a clear actionable guide using this format:

1. Summary - briefly describe the issue or request
2. What you need to do - clear step by step instructions on how to handle this
3. Expected Outcome - what should happen after following the steps
4. Best Practices - any recommendations to keep in mind

Important rules:
- Carefully read ALL chunks before answering
- Write in instructional voice - "you need to do this" not "we did this"
- Combine information from multiple chunks if the answer is spread across them
- Ignore chunks that are completely unrelated to the question
- If NONE of the chunks are relevant to the question, respond exactly with: "No past tickets found for this issue. Please escalate to senior DBA."
- Never make up information that is not in the context
- Keep instructions clear, technical but easy to follow

Context: {context}"""
def format_docs(docs):
    formatted = []
    for i, doc in enumerate(docs):
        formatted.append(f"Result {i+1}:\n{doc.page_content}\n---")
    return "\n\n".join(formatted)

def get_answer(question, retriever):
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=os.getenv("OPENAI_API_KEY")
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])
    chain = {"context": retriever | format_docs, "question": RunnablePassthrough()} | prompt | llm | StrOutputParser()
    return chain.invoke(question)


    