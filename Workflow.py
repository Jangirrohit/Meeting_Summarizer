from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3  
from langgraph.prebuilt import tools_condition
from langgraph.types import interrupt, Command
 
from utils import GraphState, transcribe, extract_node, final_node, tool_agent_node, tool_node, structured_llm, get_assignee_email_and_initialize_messages


def Human_review_node(state: GraphState):
    review_data= {
        "summary": state["summary"],
        "action_items": state["action_items"]
    }
    response= interrupt({
        "type": "human_review",
        "data": review_data,
    }
    )
    return response

def review_router(state: GraphState):
    if state.get("approved"):
        return "get_email_and_init_messages"
    if state.get("retry_count", 0) >=2:
        return "get_email_and_init_messages"
    else:
        return "re_extract"
    
def re_extract_node(state: GraphState):
    transcript= state["transcript"]
    summary= state["summary"]
    action_items= state["action_items"]
    feedback= state.get("feedback")
    prompt= f"""
        You previously extracted the following summary and action items from the transcript:
        Summary: {summary}
        Action Items: {action_items}
        The human reviewer has provided the following feedback for improvement:
        {feedback}
        Please re-extract the summary and action items from the transcript, taking into account the feedback for improvement.
        Transcript: {transcript}
        Rules: 
        - Fix mistakes using feedback
        - remove irrelevant items
        - Max 5 action items
    """

    result= structured_llm.invoke(prompt)
    action_items= [item.model_dump() for item in result.action_items]
    re= {
        "summary": result.summary,
        "action_items": action_items,
        "retry_count": state.get("retry_count", 0) + 1
    }
    return re
    
def router(state: GraphState):
    if state["transcript_format"] == "audio":
        return "audio"
    else:
        return "text"


# workflow
builder = StateGraph(GraphState)


builder.add_node("transcribe", transcribe)
builder.add_node("extract", extract_node)
builder.add_node("human_review", Human_review_node)
builder.add_node("re_extract", re_extract_node)
builder.add_node("get_email_and_init_messages", get_assignee_email_and_initialize_messages)
builder.add_node("agent", tool_agent_node)
builder.add_node("tools", tool_node)
builder.add_node("final", final_node)


builder.add_conditional_edges(
    START,
    router,
    {
        "audio": "transcribe",
        "text": "extract"
    }
)
builder.add_edge("transcribe", "extract")
builder.add_edge("extract", "human_review")
builder.add_conditional_edges(
    "human_review",
    review_router
)
builder.add_edge("re_extract", "get_email_and_init_messages")
builder.add_edge("get_email_and_init_messages", "agent")
builder.add_conditional_edges(
    "agent",
    tools_condition, 
    {
        "tools": "tools",
        "__end__": "final" 
    }
)

builder.add_edge("tools", "agent")

builder.add_edge("final", END)

checkpoint= InMemorySaver()
graph = builder.compile(checkpointer=checkpoint)


