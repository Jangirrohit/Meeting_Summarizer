## imports 
import operator
from typing import Annotated
from langchain_core.messages import BaseMessage, HumanMessage 
from langgraph.graph.message import add_messages
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import re
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3 
from langgraph.prebuilt import ToolNode 
from pydantic import BaseModel, Field
from typing import Literal, Optional, List
import json
import os
from groq import Groq
from langchain_groq import ChatGroq
from tools import tools 

from dotenv import load_dotenv
load_dotenv()


## Creating Schema for the action items and the extracted data from the meeting notes. This will be used to structure the output from the LLM and make it easier to parse and use in downstream applications.
class ActionItem(BaseModel):
    title: str = Field(description="title of the task")
    task: str = Field(description="a detailed task description")
    assignee: Optional[str] = Field(default=None, description="Specific person responsible for the task; avoid vague terms like 'team' unless explicitly stated")
    deadline: Optional[str] = Field(default=None, description="Deadline or time reference for the task or event time etc., if any")
    type: str = Field(description="Type of action: email | meeting | reminder | general")
    priority: Literal["low", "medium", "high"] = Field(default="medium", description="Priority level of the task")

class ExtractedData(BaseModel):
    summary: str = Field(
        description=(
        "Write a structured meeting summary with the following sections:\n"
        "- Topics Discussed\n"
        "- Key Decisions\n"
        "- Outcomes / Next Steps\n\n"
        "Keep it concise, factual, and avoid adding information not present in the meeting."
        )
    )

    participants: List[str] = Field(
        description=(
        "List of participant names exactly as mentioned in the meeting. "
        "Use full names if available. Avoid abbreviations unless explicitly used."
        )
    )
    
    action_items: List[ActionItem] = Field(
        default_factory=list,
        description = "Extract concise action items. Merge tasks per person. No vague or duplicate items. Return [] if none."    
        )
    

# Graph State for the Workflow
class GraphState(dict):
    transcript: Optional[str]
    audio_file: Optional[str]
    transcript_format: str
    summary: Optional[str]
    action_items: Optional[List[dict]]
    
    messages: Annotated[list[BaseMessage], add_messages]
    final_summary: str
    feedback: Optional[Annotated[List[str], operator.add]]
    approved: Optional[bool]
    retry_count: int 


## LLMs setup
load_dotenv()
llm_plain = ChatGroq(
    model="qwen/qwen3-32b",
)


## LLM for structured output (Meeting summary, action items, participants etc).
structured_llm = llm_plain.with_structured_output(ExtractedData)
# Tool-enabled LLM 
llm_with_tools = llm_plain.bind_tools(tools)

# str LLM for re_extract
llm= ChatGroq(model= "openai/gpt-oss-120b")
re_extract_llm = llm.with_structured_output(ExtractedData)

# transcription function using Groq's audio transcription API. It takes the audio file from the state, sends it to the API, and returns the transcript in the state.  
def transcribe(state):
    filename= state["audio_file"]
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    with open(filename, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(filename, file.read()),
            model="whisper-large-v3",
            temperature=0,
            response_format="verbose_json",
        )
    return {"transcript": transcription.text}



# email database function to get the email of the assignee from the database if available.  
def get_email_from_db(name: str):
    db = {
        "rohit jangir": "rohit@example.com",
        "ankit sharma": "ankit@example.com",
    }
    return db.get(name.lower().strip(), "22B1502@iitb.ac.in")

# extract_node is the main node in the graph where we use the structured_llm to extract the summary, action items and participants from the transcript.  
def extract_node(state: GraphState):
    result: ExtractedData = structured_llm.invoke(state["transcript"])
    action_items= [item.model_dump() for item in result.action_items]
    re= {
        "summary": result.summary,
        "action_items": action_items,
        "retry_count":0
    }
    return re


def get_assignee_email_and_initialize_messages(state: GraphState):
    action_items = state["action_items"]
    for item in action_items:
        assignee = item.get("assignee")
        if assignee:
            email = get_email_from_db(assignee) if assignee else None
            item["assignee_email"] = email
    re= {"action_items": action_items}
    if not state.get("messages", []):
        prompt = f"""
            Process the following action items using tools as needed.
            {json.dumps(re["action_items"], indent=2)}
        """  
        re['messages'] = [HumanMessage(content=prompt)]
    return re

# The prompt template for the tool-enabled LLM. This template provides detailed instructions to the LLM on how to process the action items, when to use tools, and how to handle missing information or failures. It emphasizes a structured and concise approach, ensuring that the LLM focuses on actionable outputs and tool usage rather than reasoning or assumptions.
template = ChatPromptTemplate(
    [
        ("system", """You are an AI agent with access to tools.

GENERAL RULES:
- Do NOT include any <think> tags
- Do NOT show reasoning
- Be concise and action-oriented
- Use tools whenever required to complete tasks
- Do NOT assume missing information

WORKFLOW:
1. Carefully analyze the provided action items
2. For each action item, decide required actions
3. Execute actions using tools step-by-step

PARTICIPANT HANDLING:
- assignee_email is already provided when available
- Do NOT attempt to resolve emails again

TIME HANDLING:
- If any action involves date/time → MUST call get_current_datetime FIRST
- Normalize relative times (e.g., "tomorrow", "next week") before using tools

ACTION RULES:
For each action item:
- If assignee exists AND email is resolved → send email using Gmail tool
- If type == "meeting" → create calendar event
- If deadline exists → create calendar reminder
- If multiple conditions apply → perform ALL relevant actions

FAILURE HANDLING:
- If required information is missing → skip that action
- Do NOT guess or hallucinate missing fields
- Continue processing remaining action items

OUTPUT:
- Only return tool outputs or final concise confirmations
"""),
        MessagesPlaceholder(variable_name="messages"),
    ]
)



# This is the node where the tool-enabled LLM processes the action items and executes the necessary tools based on the instructions provided in the prompt template. The LLM will analyze each action item, determine the required actions, and use the tools to perform those actions while adhering to the rules and workflow defined in the system message of the prompt template.  
def tool_agent_node(state: GraphState):
    prompt_value = template.invoke({
        "messages": state["messages"]
    })

    response = llm_with_tools.invoke(
         prompt_value
    )
    
    return {
        "messages": [response]
        }

tool_node = ToolNode(tools, handle_tool_errors=True)


# final node to generate the final summary by taking all the inputs from the above 
def remove_think(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
def final_node(state: GraphState):
    
    summary=state["summary"]
    action_items= state["action_items"]
    prompt= f" Given the following meeting summary and action items, generate a detailed report that includes the main points and the action items in a clear format.\n\nSummary:\n{summary}\n\nAction Items:\n{json.dumps(action_items, indent=2)}\n\nFinal Summary:"
    final_summary = remove_think(llm_plain.invoke(prompt).content)
    return {
        "final_summary": final_summary,
    }