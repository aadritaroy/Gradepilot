"""Persistence and AI helpers for GradePilot."""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import base64

from PIL import Image, UnidentifiedImageError


MAX_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_upload(name, mime_type, content):
    """Validate and normalize one uploaded image or PDF."""
    if not content:
        raise ValueError(f"{name}: the file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"{name}: files must be 20 MB or smaller.")
    suffix = Path(name).suffix.lower()
    if mime_type == "application/pdf" or suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"{name}: this does not look like a valid PDF.")
        return "application/pdf"
    if mime_type not in ALLOWED_IMAGE_TYPES and suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError(f"{name}: use a PNG, JPG, WebP, or PDF file.")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
            detected = Image.MIME.get(image.format)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError(f"{name}: the image could not be read.") from error
    if detected not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"{name}: use a PNG, JPG, or WebP image.")
    return detected


def group_uploads(files):
    """Group multiple pages by filename prefix before '__'; unmarked files stand alone."""
    groups = {}
    for item in files:
        name = item["name"]
        stem = Path(name).stem
        prefix = stem.split("__", 1)[0].strip() if "__" in stem else stem
        key = re.sub(r"[^a-zA-Z0-9_-]+", " ", prefix).strip() or stem
        groups.setdefault(key, []).append(item)
    return groups


class GradePilotStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self):
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                class_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                due_date TEXT,
                max_points INTEGER NOT NULL,
                rubric TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                student_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Needs review',
                ai_score REAL,
                ai_feedback TEXT,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                final_score REAL,
                final_feedback TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                content BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS grade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                score REAL NOT NULL,
                feedback TEXT NOT NULL,
                changed_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self):
        self.connection.close()

    def create_assignment(self, title, class_name, subject, due_date, max_points, rubric):
        cursor = self.connection.execute(
            """INSERT INTO assignments
               (title, class_name, subject, due_date, max_points, rubric, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title.strip(), class_name.strip(), subject.strip(), due_date or None,
             int(max_points), rubric.strip(), utc_now()),
        )
        self.connection.commit()
        return cursor.lastrowid

    def assignments(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM assignments ORDER BY created_at DESC, id DESC"
        )]

    def assignment(self, assignment_id):
        row = self.connection.execute(
            "SELECT * FROM assignments WHERE id = ?", (assignment_id,)
        ).fetchone()
        return dict(row) if row else None

    def add_submissions(self, assignment_id, grouped_files):
        """Persist one submission per grouped student, with all supplied pages."""
        created_ids = []
        try:
            for student_name, files in grouped_files.items():
                if not student_name.strip() or not files:
                    raise ValueError("Each submission needs a student name and at least one file.")
                cursor = self.connection.execute(
                    """INSERT INTO submissions (assignment_id, student_name, created_at)
                       VALUES (?, ?, ?)""",
                    (assignment_id, student_name.strip(), utc_now()),
                )
                submission_id = cursor.lastrowid
                created_ids.append(submission_id)
                for item in files:
                    mime_type = validate_upload(item["name"], item["mime_type"], item["content"])
                    self.connection.execute(
                        """INSERT INTO attachments (submission_id, filename, mime_type, content)
                           VALUES (?, ?, ?, ?)""",
                        (submission_id, item["name"], mime_type, item["content"]),
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return created_ids

    def submissions(self, assignment_id=None, status=None):
        query = """SELECT s.*, a.title AS assignment_title, a.class_name, a.subject,
                          a.max_points, a.rubric,
                          (SELECT COUNT(*) FROM attachments p WHERE p.submission_id = s.id) AS page_count
                   FROM submissions s JOIN assignments a ON a.id = s.assignment_id"""
        clauses, params = [], []
        if assignment_id is not None:
            clauses.append("s.assignment_id = ?")
            params.append(assignment_id)
        if status and status != "All":
            clauses.append("s.status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY CASE s.status WHEN 'Needs review' THEN 0 ELSE 1 END, s.created_at DESC, s.id DESC"
        return [dict(row) for row in self.connection.execute(query, params)]

    def submission(self, submission_id):
        row = self.connection.execute(
            """SELECT s.*, a.title AS assignment_title, a.class_name, a.subject,
                      a.max_points, a.rubric
               FROM submissions s JOIN assignments a ON a.id = s.assignment_id
               WHERE s.id = ?""",
            (submission_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["attachments"] = [
            dict(item) for item in self.connection.execute(
                "SELECT * FROM attachments WHERE submission_id = ? ORDER BY id",
                (submission_id,),
            )
        ]
        return result

    def save_suggestion(self, submission_id, score, feedback, evidence):
        submission = self.submission(submission_id)
        if not submission:
            raise ValueError("Submission not found.")
        if submission["status"] == "Approved":
            raise ValueError("An AI suggestion cannot replace an approved grade.")
        self.connection.execute(
            """UPDATE submissions SET ai_score = ?, ai_feedback = ?, evidence_json = ?,
                      status = 'Needs review' WHERE id = ?""",
            (float(score), feedback.strip(), json.dumps(evidence), submission_id),
        )
        self.connection.execute(
            """INSERT INTO grade_history
               (submission_id, action, score, feedback, changed_at)
               VALUES (?, 'ai_proposal', ?, ?, ?)""",
            (submission_id, float(score), feedback.strip(), utc_now()),
        )
        self.connection.commit()

    def approve(self, submission_id, score, feedback):
        row = self.submission(submission_id)
        if not row:
            raise ValueError("Submission not found.")
        score = float(score)
        if not 0 <= score <= row["max_points"]:
            raise ValueError(f"Score must be between 0 and {row['max_points']}.")
        self.connection.execute(
            """UPDATE submissions SET final_score = ?, final_feedback = ?,
                      status = 'Approved', approved_at = ? WHERE id = ?""",
            (score, feedback.strip(), utc_now(), submission_id),
        )
        self.connection.execute(
            """INSERT INTO grade_history
               (submission_id, action, score, feedback, changed_at)
               VALUES (?, 'teacher_approved', ?, ?, ?)""",
            (submission_id, score, feedback.strip(), utc_now()),
        )
        self.connection.commit()

    def grade_history(self, submission_id):
        return [dict(row) for row in self.connection.execute(
            """SELECT action, score, feedback, changed_at FROM grade_history
               WHERE submission_id = ? ORDER BY id""",
            (submission_id,),
        )]

    def analytics(self):
        row = self.connection.execute(
            """SELECT COUNT(*) AS submission_count,
                      SUM(CASE WHEN status = 'Approved' THEN 1 ELSE 0 END) AS approved_count,
                      AVG(CASE WHEN status = 'Approved' THEN final_score END) AS average_score
               FROM submissions"""
        ).fetchone()
        by_class = [dict(item) for item in self.connection.execute(
            """SELECT a.class_name, COUNT(s.id) AS graded_count,
                      AVG(s.final_score) AS average_score
               FROM submissions s JOIN assignments a ON a.id = s.assignment_id
               WHERE s.status = 'Approved'
               GROUP BY a.class_name ORDER BY a.class_name"""
        )]
        by_assignment = [dict(item) for item in self.connection.execute(
            """SELECT a.title, a.class_name, COUNT(s.id) AS graded_count,
                      AVG(s.final_score) AS average_score, a.max_points
               FROM assignments a LEFT JOIN submissions s
                 ON s.assignment_id = a.id AND s.status = 'Approved'
               GROUP BY a.id ORDER BY a.created_at DESC"""
        )]
        result = dict(row)
        result["approved_count"] = result["approved_count"] or 0
        result["by_class"] = by_class
        result["by_assignment"] = by_assignment
        return result


def configured_provider():
    """Return active provider and model; keys are read only on the server."""
    def has_real_secret(name):
        value = os.environ.get(name, "").strip()
        return bool(value) and not value.lower().startswith(
            ("your_", "hf_your_", "replace_me", "placeholder")
        )

    preferred = os.environ.get("AI_PROVIDER", "").strip().lower()
    if preferred == "gemini" and has_real_secret("GEMINI_API_KEY"):
        return "gemini", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if preferred in ("huggingface", "hf") and has_real_secret("HF_TOKEN"):
        return "huggingface", os.environ.get(
            "HF_GRADING_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"
        )
    if has_real_secret("GEMINI_API_KEY"):
        return "gemini", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if has_real_secret("HF_TOKEN"):
        return "huggingface", os.environ.get(
            "HF_GRADING_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"
        )
    return None, None


def _grading_prompt(submission):
    return (
        "You are assisting a teacher. Carefully assess the attached student work using only "
        "the assignment and rubric below. Return JSON with keys score (number), feedback "
        "(constructive student-facing text), and evidence (array of short observations tied "
        "to visible work). Do not infer facts that are not visible. If handwriting or pages "
        "are unclear, say so and lower confidence in the feedback, not the score without evidence. "
        "The teacher must review and approve your suggestion.\n\n"
        f"Assignment: {submission['assignment_title']}\n"
        f"Subject/class: {submission['subject']} / {submission['class_name']}\n"
        f"Maximum score: {submission['max_points']}\n"
        f"Rubric:\n{submission['rubric']}\n"
        f"Student label: {submission['student_name']}\n"
    )


def _parse_grade(text, max_points):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("The AI response did not contain the expected grading JSON.")
    try:
        data = json.loads(match.group(0))
        score = float(data["score"])
        feedback = str(data["feedback"]).strip()
        evidence = data.get("evidence", [])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("The AI returned an incomplete grading result. Try again or grade manually.") from error
    if not 0 <= score <= max_points or not feedback or not isinstance(evidence, list):
        raise ValueError("The AI returned an invalid score or feedback. Try again or grade manually.")
    return score, feedback, [str(item) for item in evidence]


def _gemini_grade(submission, model):
    api_key = os.environ["GEMINI_API_KEY"]
    parts = [{"text": _grading_prompt(submission)}]
    for attachment in submission["attachments"]:
        parts.append({
            "inline_data": {
                "mime_type": attachment["mime_type"],
                "data": base64.b64encode(attachment["content"]).decode("ascii"),
            }
        })
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:700]
        raise RuntimeError(f"Gemini request failed ({error.code}): {detail}") from None
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Gemini could not be reached: {error}") from None
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("Gemini returned no grading response. Check model access and uploaded files.") from error
    return _parse_grade(text, submission["max_points"])


def _huggingface_grade(submission, model):
    try:
        from huggingface_hub import InferenceClient

        content = [{"type": "text", "text": _grading_prompt(submission)}]
        for attachment in submission["attachments"]:
            if attachment["mime_type"] == "application/pdf":
                raise RuntimeError(
                    "The selected Hugging Face vision model cannot reliably inspect PDF uploads. "
                    "Use Gemini for PDF grading, or upload page images."
                )
            image_data = base64.b64encode(attachment["content"]).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{attachment['mime_type']};base64,{image_data}"
                },
            })
        response = InferenceClient(
            model=model, token=os.environ["HF_TOKEN"], timeout=120
        ).chat_completion(
            messages=[{"role": "user", "content": content}],
            max_tokens=700,
            temperature=0.2,
        )
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(
            "Hugging Face grading failed. Confirm your token, model/provider access, and try again. "
            f"Details: {error}"
        ) from None
    try:
        text = response.choices[0].message.content
        if isinstance(text, list):
            text = "\n".join(str(part.get("text", "")) for part in text if isinstance(part, dict))
    except (AttributeError, IndexError, TypeError) as error:
        raise RuntimeError("Hugging Face returned no grading response.") from error
    return _parse_grade(text, submission["max_points"])


def suggest_grade(submission, provider, model):
    if not submission["attachments"]:
        raise ValueError("This submission has no attached work to assess.")
    if provider == "gemini":
        return _gemini_grade(submission, model)
    if provider == "huggingface":
        return _huggingface_grade(submission, model)
    raise RuntimeError("No AI provider is configured. Configure Gemini or Hugging Face, or grade manually.")
