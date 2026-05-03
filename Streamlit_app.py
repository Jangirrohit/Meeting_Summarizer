import streamlit as st
from langgraph.types import Command
from Workflow import graph

st.set_page_config(page_title="Meeting Summarizer (HITL)", layout="wide")

# Session state init
if "result" not in st.session_state:
    st.session_state.result = None
if "thread_id" not in st.session_state:
    st.session_state.thread_id = "user"
if "waiting_for_review" not in st.session_state:
    st.session_state.waiting_for_review = False

st.title("Meeting Summarizer with Human-in-the-Loop")

# Input section
mode = st.radio("Select Input Type", ["Audio", "Text"])

input_data = {}

if mode == "Audio":
    audio_file = st.file_uploader("Upload audio file", type=None)
    if audio_file:
        with open("temp_audio.mp3", "wb") as f:
            f.write(audio_file.read())
        input_data = {
            "audio_file": "temp_audio.mp3",
            "transcript_format": "audio"
        }
else:
    transcript = st.text_area("Paste meeting transcript", height=250)
    if transcript:
        input_data = {
            "transcript": transcript,
            "transcript_format": "text"
        }

# Run button
if st.button("Run Workflow"):
    if input_data:
        result = graph.invoke(
            input_data,
            config={"configurable": {"thread_id": st.session_state.thread_id}}
        )
        st.session_state.result = result
        st.session_state.waiting_for_review = "__interrupt__" in result
    else:
        st.warning("Please provide input")

# Handle interrupt (HITL)
if st.session_state.waiting_for_review and st.session_state.result:
    interrupt_data = st.session_state.result["__interrupt__"][0].value["data"]

    st.subheader("Summary")
    st.write(interrupt_data["summary"])

    st.subheader("Action Items")
    for i, action in enumerate(interrupt_data["action_items"], start=1):
        st.markdown(f"### {i}. {action.get('title', 'No Title')}")
        
        st.markdown(f"- **Task:** {action.get('task', '')}")
        st.markdown(f"- **Assignee:** {action.get('assignee', '')}")
        st.markdown(f"- **Priority:** {action.get('priority', '')}")
        st.markdown(f"- **Type:** {action.get('type', '')}")
        
        if action.get("deadline"):
            st.markdown(f"- **Deadline:** {action.get('deadline')}")
        
        st.markdown("---")

    decision = st.radio("Approve these actions?", ["Yes", "No"])

    feedback = ""
    if decision == "No":
        feedback = st.text_area("Provide feedback")

    if st.button("Submit Review"):
        if decision == "Yes":
            resume_data = {"approved": True}
        else:
            resume_data = {"approved": False, "feedback": feedback}

        result = graph.invoke(
            Command(resume=resume_data),
            config={"configurable": {"thread_id": st.session_state.thread_id}}
        )

        st.session_state.result = result
        st.session_state.waiting_for_review = "__interrupt__" in result

# Final output
if st.session_state.result and not st.session_state.waiting_for_review:
    result = st.session_state.result

    st.subheader("🎯 Final Output")

    if isinstance(result, dict):
        for key, value in result.items():
            with st.expander(f"{key}", expanded=False):
                if isinstance(value, (dict, list)):
                    st.json(value)
                else:
                    st.write(value)
    else:
        st.write(result)
