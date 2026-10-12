import json
from io import BytesIO
from pathlib import Path
import zipfile

from dotenv import load_dotenv
import pandas as pd
import streamlit as st

from gradepilot import GradePilotStore, configured_provider, group_uploads, suggest_grade
from materials import MATERIAL_TYPES, generate_materials, material_images


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
    st.caption("TEACHER WORKSPACE")
    page = st.radio(
        "Workspace",
        ["Create materials", "Grade papers", "Grade export", "Class insights", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    if provider:
        st.success(f"AI connected · {provider.title()}", icon="✳️")
    else:
        st.info("Add an AI key to generate materials", icon="ℹ️")
    st.caption("Create → Review → Enter grades in your LMS")


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


def _assignment_paste_text(material):
    lines = [material["title"], "", material["directions"], ""]
    for question in material["questions"]:
        lines.extend([
            f"{question['number']}. {question['prompt']} ({question['points']:g} points)",
            "",
        ])
    return "\n".join(lines).strip()


def _image_download(pages, base_name):
    if len(pages) == 1:
        return pages[0]
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for index, page in enumerate(pages, 1):
            zipped.writestr(f"{base_name}-page-{index}.png", page)
    return archive.getvalue()


def _image_download_name(pages, base_name):
    return f"{base_name}.png" if len(pages) == 1 else f"{base_name}-pages.zip"


if page == "Create materials":
    title_block(
        "Assessment studio",
        "Build your next assignment.",
        "Start with the learning target or paste a rubric. Generate an assignment, worksheet, quiz, or practice quiz—with a scoring rubric and answer key.",
    )
    if not provider:
        st.warning(
            "AI generation is not enabled. Add a Gemini or Hugging Face token in `.env` "
            "to create materials. This tool does not substitute sample content."
        )

    with st.container(border=True):
        with st.form("material_generator", border=False):
            c1, c2, c3 = st.columns(3)
            material_type = c1.selectbox("Material type", MATERIAL_TYPES)
            subject = c2.text_input("Subject", placeholder="e.g. Grade 8 science")
            grade_level = c3.text_input("Grade / learner level", placeholder="e.g. Grade 8")
            c4, c5 = st.columns(2)
            class_name = c4.text_input("Class / course (optional)", placeholder="e.g. Period 3")
            difficulty = c5.selectbox("Difficulty", ["Foundational", "On level", "Challenge"])
            c6, c7 = st.columns(2)
            question_count = c6.number_input("Number of questions", min_value=1, max_value=30, value=5)
            max_points = c7.number_input("Total points", min_value=1, max_value=200, value=20)
            instructions = st.text_area(
                "What should students learn or demonstrate?",
                placeholder="Example: Assess understanding of forces and motion. Include free-body diagrams, net force, and one real-world explanation question.",
                height=120,
            )
            source_rubric = st.text_area(
                "Optional: paste an existing rubric or scoring guide",
                placeholder="Paste criteria here to guide the generated questions and rubric.",
                height=100,
            )
            generate_clicked = st.form_submit_button(
                "Generate assignment, rubric & answer key",
                type="primary",
                use_container_width=True,
                disabled=not bool(provider),
            )

    if generate_clicked:
        if not subject.strip() or not grade_level.strip() or not instructions.strip():
            st.error("Add a subject, grade level, and learning target or instructions.")
        else:
            try:
                with st.spinner(f"Creating {material_type.lower()} materials with {provider.title()}…"):
                    generated = generate_materials(
                        instructions=instructions,
                        material_type=material_type,
                        subject=subject,
                        grade_level=grade_level,
                        difficulty=difficulty,
                        question_count=int(question_count),
                        max_points=int(max_points),
                        source_rubric=source_rubric,
                        provider=provider,
                        model=ai_model,
                    )
            except (RuntimeError, ValueError, KeyError, TypeError) as error:
                st.error(f"Material generation failed: {error}")
            else:
                st.session_state.generated_material_package = {
                    "material": generated,
                    "material_type": material_type,
                    "subject": subject.strip(),
                    "class_name": class_name.strip() or f"{grade_level.strip()} · Materials library",
                    "grade_level": grade_level.strip(),
                    "difficulty": difficulty,
                    "instructions": instructions.strip(),
                }
                st.session_state.generated_package_saved = False
                st.success("Generated with AI. Review the assignment before using it.")

    package = st.session_state.get("generated_material_package")
    if package:
        generated = package["material"]
        st.divider()
        st.markdown(f"## {generated['title']}")
        st.caption(
            f"{package['subject']} · {package['grade_level']} · "
            f"{package['material_type']} · {generated['max_points']} points"
        )
        output_images = material_images(
            generated,
            package["subject"],
            package["grade_level"],
            package["material_type"],
        )

        assignment_tab, rubric_tab, key_tab = st.tabs(
            ["Student assignment", "Rubric · image only", "Answer key · image only"]
        )
        with assignment_tab:
            assignment_pages = output_images["assignment"]
            for page_number, image_bytes in enumerate(assignment_pages, 1):
                st.image(image_bytes, caption=f"Assignment page {page_number}", use_container_width=True)
            st.download_button(
                "Download assignment image(s)",
                data=_image_download(assignment_pages, "assignment"),
                file_name=_image_download_name(assignment_pages, "assignment"),
                mime="image/png" if len(assignment_pages) == 1 else "application/zip",
                use_container_width=True,
            )
            paste_text = _assignment_paste_text(generated)
            st.download_button(
                "Download paste-ready assignment text",
                data=paste_text.encode("utf-8"),
                file_name="assignment.txt",
                mime="text/plain",
                use_container_width=True,
            )
            st.text_area(
                "Paste-ready assignment for Docs or Word",
                value=paste_text,
                height=300,
                help="Select and copy this student-facing version. The answer key and rubric are not included.",
            )
        with rubric_tab:
            rubric_pages = output_images["rubric"]
            for page_number, image_bytes in enumerate(rubric_pages, 1):
                st.image(image_bytes, caption=f"Rubric image {page_number}", use_container_width=True)
            st.download_button(
                "Download rubric image(s)",
                data=_image_download(rubric_pages, "rubric"),
                file_name=_image_download_name(rubric_pages, "rubric"),
                mime="image/png" if len(rubric_pages) == 1 else "application/zip",
                use_container_width=True,
            )
        with key_tab:
            key_pages = output_images["answer_key"]
            for page_number, image_bytes in enumerate(key_pages, 1):
                st.image(image_bytes, caption=f"Answer key image {page_number}", use_container_width=True)
            st.download_button(
                "Download answer key image(s)",
                data=_image_download(key_pages, "answer-key"),
                file_name=_image_download_name(key_pages, "answer-key"),
                mime="image/png" if len(key_pages) == 1 else "application/zip",
                use_container_width=True,
            )

        if st.button(
            "Save materials to grading library",
            type="primary",
            key="save_generated_materials",
            disabled=st.session_state.get("generated_package_saved", False),
        ):
            rubric_for_grading = "\n".join(
                f"{item['criterion']} ({item['points']:g} points): {item['description']}"
                for item in generated["rubric"]
            )
            store.create_assignment(
                generated["title"],
                package["class_name"],
                package["subject"],
                "",
                generated["max_points"],
                rubric_for_grading,
                material_type=package["material_type"],
                instructions=package["instructions"],
                materials_json=json.dumps(generated),
            )
            st.session_state.generated_package_saved = True
            st.success("Saved. This rubric is now available in the grading workflow.")
        elif st.session_state.get("generated_package_saved"):
            st.caption("Saved to the grading library.")

    st.divider()
    st.markdown("### Saved assessment library")
    assignments = store.assignments()
    if assignments:
        for assignment in assignments:
            with st.expander(
                f"{assignment['title']} · {assignment['material_type']} · "
                f"{assignment['subject']} · {assignment['max_points']} pts"
            ):
                st.caption(assignment["class_name"])
                if assignment["materials_json"]:
                    try:
                        saved_material = json.loads(assignment["materials_json"])
                    except json.JSONDecodeError:
                        st.error("Saved material data is unreadable.")
                    else:
                        saved_images = material_images(
                            saved_material,
                            assignment["subject"],
                            assignment["class_name"],
                            assignment["material_type"],
                        )
                        assignment_tab, rubric_tab, key_tab = st.tabs(
                            ["Assignment", "Rubric image", "Answer key image"]
                        )
                        with assignment_tab:
                            st.text_area(
                                "Paste-ready assignment",
                                value=_assignment_paste_text(saved_material),
                                height=220,
                                key=f"saved_text_{assignment['id']}",
                            )
                            st.download_button(
                                "Download paste-ready assignment text",
                                data=_assignment_paste_text(saved_material).encode("utf-8"),
                                file_name="assignment.txt",
                                mime="text/plain",
                                key=f"saved_text_file_{assignment['id']}",
                            )
                            saved_pages = saved_images["assignment"]
                            st.download_button(
                                "Download assignment image(s)",
                                data=_image_download(saved_pages, "assignment"),
                                file_name=_image_download_name(saved_pages, "assignment"),
                                mime="image/png" if len(saved_pages) == 1 else "application/zip",
                                key=f"saved_assignment_{assignment['id']}",
                            )
                        for target_tab, asset_name, label, archive_name in (
                            (rubric_tab, "rubric", "rubric", "rubric"),
                            (key_tab, "answer_key", "answer key", "answer-key"),
                        ):
                            with target_tab:
                                saved_pages = saved_images[asset_name]
                                for page_number, image_bytes in enumerate(saved_pages, 1):
                                    st.image(
                                        image_bytes,
                                        caption=f"{label.title()} image {page_number}",
                                        use_container_width=True,
                                    )
                                st.download_button(
                                    f"Download {label} image(s)",
                                    data=_image_download(saved_pages, archive_name),
                                    file_name=_image_download_name(saved_pages, archive_name),
                                    mime="image/png" if len(saved_pages) == 1 else "application/zip",
                                    key=f"saved_{asset_name}_{assignment['id']}",
                                )
                else:
                    st.caption("Legacy assessment without saved generated materials.")
    else:
        st.caption("Your generated materials will appear here after you save them.")

    st.divider()
    st.markdown("### Add student work for automatic grading")
    if not assignments:
        st.info("Save generated materials first; their rubric will be used when grading papers.")
    else:
        assignment_by_label = {
            f"{item['title']} · {item['subject']} (#{item['id']})": item
            for item in assignments
        }
        selected_label = st.selectbox("Assessment", list(assignment_by_label))
        st.caption(
            "Each file is treated as one student submission. To group pages, use names "
            "such as `Jordan Lee__page1.jpg` and `Jordan Lee__page2.jpg`."
        )
        uploads = st.file_uploader(
            "Upload student papers",
            type=["png", "jpg", "jpeg", "webp", "pdf"],
            accept_multiple_files=True,
            key="submission_uploads",
        )
        grouped = group_uploads([
            {"name": item.name, "mime_type": item.type, "content": item.getvalue()}
            for item in uploads
        ]) if uploads else {}
        if grouped:
            st.caption(f"{len(uploads)} file(s) · {len(grouped)} student submission(s)")
            st.dataframe(
                pd.DataFrame([
                    {"Student / group": name, "Pages": len(items),
                     "Files": ", ".join(item["name"] for item in items)}
                    for name, items in grouped.items()
                ]),
                hide_index=True,
                use_container_width=True,
            )
        if st.button("Save papers to grading queue", type="primary", disabled=not bool(grouped)):
            try:
                ids = store.add_submissions(assignment_by_label[selected_label]["id"], grouped)
            except (ValueError, OSError) as error:
                st.error(f"Upload not saved: {error}")
            else:
                st.success(f"Added {len(ids)} student submission(s) to the grading queue.")
                st.rerun()


elif page == "Grade papers":
    title_block("Teacher review", "Grade papers", "AI prepares a rubric-based draft. You review and approve every final score.")
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


elif page == "Grade export":
    title_block(
        "Manual LMS entry",
        "Approved grades",
        "Review approved scores in one place, then download a simple CSV to use while entering grades in Canvas or another LMS.",
    )
    approved_rows = [
        row for row in store.submissions()
        if row["status"] == "Approved" and row["final_score"] is not None
    ]
    if not approved_rows:
        st.info("No teacher-approved grades yet. Review work in Grade papers first.")
    else:
        export_data = [{
            "Student": row["student_name"],
            "Assignment": row["assignment_title"],
            "Class": row["class_name"],
            "Score": row["final_score"],
            "Out of": row["max_points"],
            "Feedback": row["final_feedback"] or "",
        } for row in approved_rows]
        export_frame = pd.DataFrame(export_data)
        st.dataframe(export_frame, hide_index=True, use_container_width=True)
        st.download_button(
            "Download approved grades CSV",
            data=export_frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="gradepilot-approved-grades.csv",
            mime="text/csv",
            type="primary",
        )
        st.caption("This file is for teacher reference and manual LMS entry; it does not write grades into Canvas.")


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
