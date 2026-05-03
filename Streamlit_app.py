import streamlit as st
from langgraph.types import Command
from Workflow import graph

st.set_page_config(page_title="Meeting Summarizer (HITL)", layout="wide")


# ----------------------------
# STATE INIT
# ----------------------------
if "state" not in st.session_state:
    st.session_state.state = "idle"  # idle | running | review | submitting | done

if "result" not in st.session_state:
    st.session_state.result = None

if "thread_id" not in st.session_state:
    st.session_state.thread_id = "user"


# ----------------------------
# CALLBACKS
# ----------------------------
def start_workflow():
    st.session_state.state = "running"


def submit_review():
    st.session_state.state = "submitting"


def reset_workflow():
    st.session_state.state = "idle"
    st.session_state.result = None


st.title("Meeting Summarizer with Human-in-the-Loop")


# ----------------------------
# INPUTS
# ----------------------------
mode = st.radio(
    "Select Input Type",
    ["Audio", "Text"],
    disabled=st.session_state.state in ["running", "submitting"],
)

input_data = {}

if mode == "Audio":
    audio_file = st.file_uploader(
        "Upload audio file",
        disabled=st.session_state.state in ["running", "submitting"],
    )

    if audio_file:
        with open("temp_audio.mp3", "wb") as f:
            f.write(audio_file.read())

        input_data = {"audio_file": "temp_audio.mp3", "transcript_format": "audio"}

else:
    transcript = st.text_area(
        "Paste meeting transcript",
        height=250,
        disabled=st.session_state.state in ["running", "submitting"],
    )

    if transcript:
        input_data = {"transcript": transcript, "transcript_format": "text"}


# ----------------------------
# SHOW RUN BUTTON ONLY IN IDLE
# ----------------------------
if st.session_state.state == "idle":
    st.button("Run Workflow", on_click=start_workflow)


# ----------------------------
# RUN WORKFLOW (button disappears immediately)
# ----------------------------
if st.session_state.state == "running":
    if not input_data:
        st.warning("Please provide input")
        st.session_state.state = "idle"
        st.stop()

    with st.spinner("Processing meeting..."):
        result = graph.invoke(
            input_data,
            config={"configurable": {"thread_id": st.session_state.thread_id}},
        )

    st.session_state.result = result

    if "__interrupt__" in result:
        st.session_state.state = "review"
    else:
        st.session_state.state = "done"

    st.rerun()


# ----------------------------
# REVIEW STATE
# ----------------------------
if st.session_state.state == "review":
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

    # button visible ONLY in review state
    st.button("Submit Review", on_click=submit_review)

    # store temporary review data
    st.session_state.review_decision = decision
    st.session_state.feedback = feedback


# ----------------------------
# SUBMIT REVIEW
# ----------------------------
if st.session_state.state == "submitting":
    if st.session_state.review_decision == "Yes":
        resume_data = {"approved": True}
    else:
        resume_data = {"approved": False, "feedback": st.session_state.feedback}

    with st.spinner("Submitting review..."):
        result = graph.invoke(
            Command(resume=resume_data),
            config={"configurable": {"thread_id": st.session_state.thread_id}},
        )

    st.session_state.result = result

    if "__interrupt__" in result:
        st.session_state.state = "review"
    else:
        st.session_state.state = "done"

    st.rerun()


# ----------------------------
# FINAL OUTPUT
# ----------------------------
if st.session_state.state == "done":
    st.subheader("🎯 Final Output")

    result = st.session_state.result

    if isinstance(result, dict):
        for key, value in result.items():
            with st.expander(key):
                if isinstance(value, (dict, list)):
                    st.json(value)
                else:
                    st.write(value)
    else:
        st.write(result)

    # old buttons stay hidden
    # only this appears
    st.button("Run New Meeting", on_click=reset_workflow)
