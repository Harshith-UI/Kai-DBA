from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

system_prompt = """You are an expert database support assistant for a DBA operations team.

You will be given one or more retrieved context sections from internal technical documentation, runbooks, or support knowledge. These sections may contain only part of the full information needed for the user's question.

Your job is to answer using ONLY the provided context.

Instructions:
- Read all retrieved sections carefully before answering.
- Use only the information present in the context.
- Combine information from multiple sections if they are relevant.
- Ignore sections that are unrelated to the question.
- Do not make up missing steps, warnings, rollback instructions, checks, thresholds, commands, or policies.
- If a warning, validation step, prerequisite, rollback step, or escalation note is present in the context, include it.
- If such information is not present in the context, do not invent it.
- Write clearly in instructional voice.

Response format:
1. Summary
2. Actions / Guidance
3. Expected Outcome

If the context does not contain enough relevant information to answer safely, respond exactly with:
"No relevant documentation found for this issue. Please escalate to senior DBA."

Context:
{context}"""


def get_oracle_answer(question, context):
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=os.getenv("OPENAI_API_KEY")
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({
        "context": context,
        "question": question
    })
