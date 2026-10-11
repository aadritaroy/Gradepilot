# GradePilot

GradePilot is a local-first teacher grading workspace built with Python and Streamlit. It includes a dashboard, rubric-based assignments, a grading inbox, image/PDF submission uploads, teacher-approved grades, and insights calculated from saved results.

## Run locally

Use Python 3.10 or newer. From this folder:

```powershell
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

Open the local URL printed by Streamlit. GradePilot creates `data/gradepilot.sqlite` on first run. Assignments, submissions, original uploads, AI suggestions, and approved grades are stored there. Back up this file securely. Local data and `.env` are excluded from Git.

## Core workflow

1. Create an assignment, class, maximum score, and rubric.
2. Upload multiple PNG, JPG, WebP, or PDF files. Each file is a submission by default. Group pages into one student submission by using names such as `Jordan Lee__page1.jpg` and `Jordan Lee__page2.jpg`; everything before `__` is the student label.
3. Review each submission in **Grading inbox**. Grade manually, or ask the configured vision model for a suggestion.
4. Edit the score and student-facing feedback, then explicitly approve the grade. Insights include only teacher-approved grades, never unreviewed AI suggestions.

There is no seeded classroom data. Empty dashboards and insights reflect the actual local database; provider failures are shown as errors and never replaced with demo results.

## Optional AI grading

AI calls are server-side and only occur when a teacher clicks **Get AI suggestion**. Choose one provider and put its key in a local `.env` file in this project directory:

```text
GEMINI_API_KEY=your_private_key
# or
HF_TOKEN=your_private_huggingface_token
```

Optional model/provider selection:

```text
AI_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-flash
# For a multimodal Hugging Face chat model:
AI_PROVIDER=huggingface
HF_GRADING_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
```

Restart Streamlit after changing `.env`. Gemini can receive image and PDF attachments. Hugging Face requires a multimodal chat model and supports image attachments in this app; PDF grading is rejected explicitly, so select Gemini or upload page images. Provider availability, model access, limits, and billing depend on your account. Keep all keys private; never paste them into the app, repository, or a shared screenshot.

Student files and rubric text are sent to the selected AI provider only when you request a suggestion. AI output is an editable draft, not a final grade. A teacher must approve every score before it is included in analytics.

## Validate

```powershell
py -m unittest discover -s tests -v
py -m py_compile app.py gradepilot.py
```

