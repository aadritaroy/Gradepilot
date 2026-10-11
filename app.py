from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
import streamlit as st

from gradepilot import GradePilotStore, configured_provider, group_uploads, suggest_grade


APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")
store = GradePilotStore(APP_DIR / "data" / "gradepilot.sqlite")
provider, ai_model = configured_provider()

st.set_page_config(
    page_title="GradePilot | Teacher workspace",
    page_icon="✳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
    :root { --ink:#182638; --muted:#697789; --teal:#087f79; --line:#e6eaed; --wash:#f4f7f7; }
    html, body, [class*="css"] { font-family:'DM Sans',sans-serif; color:var(--ink); }
    .stApp { background:#f8faf9; }
    [data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--line); }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 { font-family:Manrope,sans-serif; }
    .block-container { max-width:1440px; padding-top:1.5rem; }
    h1,h2,h3 { font-family:Manrope,sans-serif; letter-spacing:-.035em; }
    .brand { color:#182638; font:800 1.25rem Manrope,sans-serif; letter-spacing:-.06em; }
    .brand span { color:var(--teal); }
    .muted { color:var(--muted); }
    .eyebrow { color:var(--teal); text-transform:uppercase; letter-spacing:.12em; font-size:.72rem; font-weight:800; }
    .metric-note { font-size:.82rem; color:var(--muted); }
    div[data-testid="stMetric"] { background:white; border:1px solid var(--line); border-radius:14px; padding:1rem 1.1rem; }
    div[data-testid="stVerticalBlockBorderWrapper"] { background:white; border-color:var(--line); border-radius:14px; }
    .stButton > button, .stFormSubmitButton > button { border-radius:9px; font-weight:700; }
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background:#087f79; border-color:#087f79; }
    .stButton > button[kind="primary"]:hover { background:#066c67; border-color:#066c67; }
    [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown('<div class="brand">Grade<span>Pilot</span></div>', unsafe_allow_html=True)
    st.caption("Your calm, considered grading workspace")
    page = st.radio(
        "Workspace",
        ["Dashboard", "Assignments", "Grading inbox", "Class insights", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    if provider:
        st.success(f"AI ready · {provider.title()}", icon="✳️")
    else:
        st.info("AI not configured · manual grading is ready", icon="ℹ️")
    st.caption("Your work is saved locally on this device.")


def title_block(kicker, title, description):
    st.markdown(f'<div class="eyebrow">{kicker}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="muted">{description}</p>', unsafe_allow_html=True)


def show_submission_list(rows):
    if not rows:
        st.info("Nothing here yet. Add an assignment and upload student work to get started.")
        return
    display = [{
        "Student": row["student_name"],
        "Assignment": row["assignment_title"],
        "Class": row["class_name"],
        "Pages": row["page_count"],
        "Status": row["status"],
        "Score": (
            f'{row["final_score"]:g} / {row["max_points"]}'
            if row["final_score"] is not None else "—"
        ),
    } for row in rows]
    st.dataframe(pd.DataFrame(display), hide_index=True, use_container_width=True)


if page == "Dashboard":
    title_block("Teacher workspace", "Good morning. Let’s make grading lighter.",
                "A clear view of your classes, assessment work, and what needs your attention.")
    submissions = store.submissions()
    insights = store.analytics()
    pending = sum(row["status"] == "Needs review" for row in submissions)
    assignment_list = store.assignments()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active assignments", len(assignment_list))
    c2.metric("To review", pending)
    c3.metric("Submissions saved", insights["submission_count"])
    c4.metric(
        "Class average",
        f'{insights["average_score"]:.1f}' if insights["average_score"] is not None else "—",
        help="Average of teacher-approved scores only.",
    )
    st.markdown("### Your grading queue")
    show_submission_list([row for row in submissions if row["status"] == "Needs review"][:8])
    st.caption("AI suggestions are never counted as grades. Insights use teacher-approved scores only.")


elif page == "Assignments":
    title_block("Plan & organize", "Assignments", "Create assessments with a rubric, then collect each student’s work.")
    with st.expander("＋ Create an assignment", expanded=not bool(store.assignments())):
        with st.form("new_assignment", clear_on_submit=True):
            left, right = st.columns(2)
            title = left.text_input("Assignment title", placeholder="e.g. Fractions: show your thinking")
            class_name = right.text_input("Class", placeholder="e.g. Grade 5 · Room 12")
            subject = left.text_input("Subject", placeholder="e.g. Mathematics")
            due_date = right.date_input("Due date", value=None)
            max_points = left.number_input("Maximum points", min_value=1, max_value=1000, value=20)
            rubric = st.text_area(
                "Rubric / success criteria",
                placeholder="List the criteria and how work will be evaluated.",
                height=140,
                help="This rubric is included when asking AI for a grading suggestion.",
            )
            submitted = st.form_submit_button("Create assignment", type="primary")
        if submitted:
            missing = [label for label, value in (
                ("title", title.strip()), ("class", class_name.strip()),
                ("subject", subject.strip()), ("rubric", rubric.strip()),
            ) if not value]
            if missing:
                st.error("Please complete: " + ", ".join(missing) + ".")
            else:
                store.create_assignment(
                    title, class_name, subject,
                    due_date.isoformat() if isinstance(due_date, date) else "",
                    max_points, rubric,
                )
                st.success(f"Created “{title.strip()}”.")
                st.rerun()

    assignments = store.assignments()
    if assignments:
        st.markdown("### Your assessments")
        for assignment in assignments:
            rows = store.submissions(assignment["id"])
            approved = sum(row["status"] == "Approved" for row in rows)
            with st.container(border=True):
                a, b, c = st.columns([4, 1.3, 1.5])
                a.markdown(f"#### {assignment['title']}")
                a.caption(f"{assignment['class_name']} · {assignment['subject']} · up to {assignment['max_points']} points")
                if assignment["due_date"]:
                    a.caption(f"Due {assignment['due_date']}")
                b.metric("Submissions", len(rows))
                c.metric("Approved", approved)
                with st.expander("View rubric"):
                    st.write(assignment["rubric"])
    else:
        st.info("Create your first assignment above. No example data is mixed into your real workspace.")

    st.markdown("### Collect student work")
    assignments = store.assignments()
    if not assignments:
        st.info("Create an assignment before uploading work.")
    else:
        with st.container(border=True):
            assignment_by_label = {
                f"{item['title']} · {item['class_name']} (#{item['id']})": item
                for item in assignments
            }
            selected_label = st.selectbox("Assignment", list(assignment_by_label))
            st.markdown(
                "Upload multiple PNG, JPG, WebP, or PDF files. One file is one submission. "
                "To group pages into a single student submission, name them "
                "`StudentName__page1.jpg`, `StudentName__page2.jpg`."
            )
            uploads = st.file_uploader(
                "Student work",
                type=["png", "jpg", "jpeg", "webp", "pdf"],
                accept_multiple_files=True,
                key="submission_uploads",
            )
            grouped = group_uploads([
                {"name": item.name, "mime_type": item.type, "content": item.getvalue()}
                for item in uploads
            ]) if uploads else {}
            if grouped:
                st.caption(f"{len(uploads)} file(s) will create {len(grouped)} submission(s).")
                st.dataframe(
                    pd.DataFrame([
                        {"Student / group": name, "Pages / files": len(items),
                         "Files": ", ".join(item["name"] for item in items)}
                        for name, items in grouped.items()
                    ]),
                    hide_index=True,
                    use_container_width=True,
                )
            if st.button("Save uploaded submissions", type="primary", disabled=not bool(grouped)):
                try:
                    ids = store.add_submissions(assignment_by_label[selected_label]["id"], grouped)
                except (ValueError, OSError) as error:
                    st.error(f"Upload not saved: {error}")
                else:
                    st.success(f"Saved {len(ids)} submission(s) with their uploaded work.")
                    st.rerun()


elif page == "Grading inbox":
    title_block("Review & decide", "Grading inbox", "See student work, use an AI suggestion when configured, and approve the grade yourself.")
    all_rows = store.submissions()
    filter_col, assignment_col = st.columns([1, 2])
    status_filter = filter_col.selectbox("Status", ["Needs review", "Approved", "All"])
    assignments = store.assignments()
    assignment_filter = assignment_col.selectbox(
        "Assignment",
        ["All assignments"] + [
            f"{a['title']} · {a['class_name']} (#{a['id']})" for a in assignments
        ],
    )
    assignment_ids = {
        f"{a['title']} · {a['class_name']} (#{a['id']})": a["id"] for a in assignments
    }
    filtered = [
        row for row in all_rows
        if (status_filter == "All" or row["status"] == status_filter)
        and (assignment_filter == "All assignments" or row["assignment_id"] == assignment_ids[assignment_filter])
    ]
    if not filtered:
        st.info("No submissions match these filters. Upload work from the Assignments page.")
    else:
        left, right = st.columns([1, 2.2], gap="large")
        selected_id = left.selectbox(
            "Select student work",
            [row["id"] for row in filtered],
            format_func=lambda sid: next(
                f"{row['student_name']} · {row['assignment_title']}"
                for row in filtered if row["id"] == sid
            ),
        )
        submission = store.submission(selected_id)
        left.markdown(f"**{submission['student_name']}**")
        left.caption(f"{submission['assignment_title']} · {submission['class_name']}")
        left.caption(f"{len(submission['attachments'])} attached page(s) · {submission['status']}")
        evidence = __import__("json").loads(submission["evidence_json"] or "[]")
        if submission["ai_score"] is not None:
            left.info(f"AI suggestion: {submission['ai_score']:g} / {submission['max_points']}")
            left.markdown(submission["ai_feedback"] or "")
            if evidence:
                left.markdown("**Evidence noted**")
                for observation in evidence:
                    left.markdown(f"- {observation}")
        if provider and submission["status"] != "Approved":
            if st.button(f"✳️ Get AI suggestion · {provider.title()}", type="primary", key=f"ai_{selected_id}"):
                try:
                    with st.spinner(f"Reviewing the work with {provider.title()}…"):
                        score, feedback, evidence = suggest_grade(submission, provider, ai_model)
                    store.save_suggestion(selected_id, score, feedback, evidence)
                    st.success("Suggestion saved for your review. It is not an approved grade.")
                    st.rerun()
                except Exception as error:
                    st.error(f"AI grading did not complete: {error}")
        elif submission["status"] == "Approved":
            st.caption("This grade is approved. Its AI proposal cannot overwrite the teacher-approved result.")
        else:
            st.caption("Add a server-side AI key in `.env` to enable suggestions. Manual grading is available now.")
        with right:
            st.markdown("### Student work")
            if not submission["attachments"]:
                st.warning("No files are attached to this submission.")
            for attachment in submission["attachments"]:
                st.caption(attachment["filename"])
                if attachment["mime_type"].startswith("image/"):
                    st.image(attachment["content"], use_container_width=True)
                else:
                    st.download_button(
                        f"Open / download {attachment['filename']}",
                        data=attachment["content"],
                        file_name=attachment["filename"],
                        mime=attachment["mime_type"],
                        key=f"pdf_{attachment['id']}",
                    )
        st.divider()
        st.markdown("### Teacher review")
        if submission["ai_score"] is not None and submission["status"] != "Approved":
            suggested_score = float(submission["ai_score"])
            suggested_feedback = submission["ai_feedback"] or ""
        else:
            suggested_score = float(submission["final_score"] or 0)
            suggested_feedback = submission["final_feedback"] or ""
        with st.form(f"approve_{selected_id}"):
            score = st.number_input(
                "Final score",
                min_value=0.0,
                max_value=float(submission["max_points"]),
                value=min(suggested_score, float(submission["max_points"])),
                step=0.5,
            )
            feedback = st.text_area(
                "Feedback for student",
                value=suggested_feedback,
                placeholder="Share a specific strength and a helpful next step.",
                height=120,
            )
            approve_clicked = st.form_submit_button("Approve grade", type="primary")
        if approve_clicked:
            if not feedback.strip():
                st.error("Add feedback before approving this grade.")
            else:
                try:
                    store.approve(selected_id, score, feedback)
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success("Grade approved and saved.")
                    st.rerun()
        history = store.grade_history(selected_id)
        if history:
            with st.expander("Grade history"):
                for entry in history:
                    st.markdown(
                        f"**{entry['action'].replace('_', ' ').title()} · "
                        f"{entry['score']:g} / {submission['max_points']}**"
                    )
                    st.caption(entry["changed_at"])
                    st.write(entry["feedback"])


elif page == "Class insights":
    title_block("Patterns, not paperwork", "Class insights", "Analytics are calculated only from saved, teacher-approved scores.")
    analytics = store.analytics()
    a, b, c = st.columns(3)
    a.metric("Submissions", analytics["submission_count"])
    b.metric("Teacher-approved", analytics["approved_count"])
    c.metric(
        "Approved average",
        f'{analytics["average_score"]:.1f}' if analytics["average_score"] is not None else "—",
        help="Raw points, not normalized across different assignment totals.",
    )
    if not analytics["by_assignment"]:
        st.info("Create assignments and approve some grades to see insights. No sample results are shown.")
    else:
        st.markdown("### By assignment")
        st.dataframe(pd.DataFrame([{
            "Assignment": item["title"],
            "Class": item["class_name"],
            "Approved": item["graded_count"],
            "Average (points)": (
                round(item["average_score"], 1) if item["average_score"] is not None else "—"
            ),
            "Out of": item["max_points"],
        } for item in analytics["by_assignment"]]), hide_index=True, use_container_width=True)
        if analytics["by_class"]:
            st.markdown("### By class")
            st.dataframe(pd.DataFrame([{
                "Class": item["class_name"],
                "Approved submissions": item["graded_count"],
                "Average (points)": round(item["average_score"], 1),
            } for item in analytics["by_class"]]), hide_index=True, use_container_width=True)
    st.caption("Student work, scores, and feedback stay in the local SQLite database. AI calls only happen when a teacher requests a suggestion.")


elif page == "Settings":
    title_block("Workspace preferences", "Settings", "Configure AI privately and understand where your classroom data lives.")
    st.markdown("### AI grading")
    if provider:
        st.success(f"{provider.title()} is configured · model `{ai_model}`.")
    else:
        st.warning("No AI provider is configured. You can still review and approve grades manually.")
    st.markdown(
        "Set credentials in a local `.env` file (never in source code or the browser). "
        "Supported variables: `GEMINI_API_KEY` and/or `HF_TOKEN`. Optional: "
        "`AI_PROVIDER=gemini` or `AI_PROVIDER=huggingface`, plus `GEMINI_MODEL` or "
        "`HF_GRADING_MODEL`. Gemini supports image and PDF input; Hugging Face grading "
        "requires a multimodal chat model and currently accepts images only."
    )
    st.markdown("### Data")
    st.code(str(APP_DIR / "data" / "gradepilot.sqlite"), language=None)
    st.caption("Assignments, uploaded files, suggested grades, teacher edits, and approvals are stored locally in SQLite. Back up this file securely. AI grading sends the selected submission and rubric to the configured provider only after you request it.")
    st.markdown("### GradePilot")
    st.write("AI feedback is an optional draft, not a final decision. Teachers review, edit, and approve every grade. AI suggestions are excluded from class analytics until approved.")
