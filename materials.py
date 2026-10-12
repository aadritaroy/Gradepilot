"""AI assessment generation and printable image rendering for GradePilot."""

import json
import os
import re
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


MATERIAL_TYPES = (
    "Assignment",
    "Worksheet",
    "Quiz",
    "Practice quiz",
)


def _parse_material_response(text, max_points, question_count=None):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("The AI response did not contain the expected materials JSON.")
    try:
        material = json.loads(match.group(0))
        title = str(material["title"]).strip()
        directions = str(material["directions"]).strip()
        questions = material["questions"]
        rubric = material["rubric"]
        if not title or not directions or not isinstance(questions, list) or not questions:
            raise ValueError("The AI response is missing a title, directions, or questions.")
        if not isinstance(rubric, list) or not rubric:
            raise ValueError("The AI response is missing rubric criteria.")
        if question_count is not None and len(questions) != question_count:
            raise ValueError(
                f"The generated material has {len(questions)} questions, not the requested "
                f"{question_count}. Try generating again."
            )
        parsed_questions = []
        for index, question in enumerate(questions, 1):
            number = str(question.get("number", index))
            prompt = str(question["prompt"]).strip()
            answer = str(question["answer"]).strip()
            points = float(question["points"])
            if not prompt or not answer or points <= 0:
                raise ValueError(f"Question {number} is incomplete or has invalid points.")
            parsed_questions.append({
                "number": number,
                "type": str(question.get("type", "Written response")).strip(),
                "prompt": prompt,
                "points": points,
                "answer": answer,
            })
        parsed_rubric = []
        for criterion in rubric:
            name = str(criterion["criterion"]).strip()
            description = str(criterion["description"]).strip()
            points = float(criterion["points"])
            if not name or not description or points <= 0:
                raise ValueError("A rubric criterion is incomplete or has invalid points.")
            parsed_rubric.append({
                "criterion": name,
                "description": description,
                "points": points,
            })
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("The AI returned incomplete assessment materials. Try again.") from error

    question_total = sum(item["points"] for item in parsed_questions)
    rubric_total = sum(item["points"] for item in parsed_rubric)
    if question_total != max_points:
        raise ValueError(
            f"The generated questions total {question_total:g} points, not the requested "
            f"{max_points:g}. Try generating again."
        )
    if rubric_total != max_points:
        raise ValueError(
            f"The generated rubric totals {rubric_total:g} points, not the requested "
            f"{max_points:g}. Try generating again."
        )
    return {
        "title": title,
        "directions": directions,
        "questions": parsed_questions,
        "rubric": parsed_rubric,
        "max_points": max_points,
    }


def _generation_prompt(
    instructions,
    material_type,
    subject,
    grade_level,
    difficulty,
    question_count,
    max_points,
    source_rubric,
):
    rubric_source = source_rubric.strip() or "No existing rubric supplied."
    return f"""Create teacher-ready {material_type.lower()} materials. Return only valid JSON with this exact shape:
{{
  "title": "concise teacher-ready title",
  "directions": "student-facing directions",
  "questions": [
    {{"number":"1","type":"Written response","prompt":"question text","points":2,"answer":"correct answer and brief reasoning"}}
  ],
  "rubric": [
    {{"criterion":"criterion name","description":"observable scoring description","points":2}}
  ]
}}

Teacher instructions or learning targets:
{instructions.strip()}

Subject: {subject}
Grade level: {grade_level}
Difficulty: {difficulty}
Material type: {material_type}
Requested question count: {question_count}
Exact maximum score: {max_points}
Optional teacher-provided rubric or criteria:
{rubric_source}

Requirements:
- Build questions and answer key directly from the teacher instructions and any supplied rubric.
- If a rubric is supplied, preserve its intent and make each criterion observable and scorable.
- Include an accurate answer for every question, including reasoning for open responses.
- Match the requested count exactly and use age-appropriate language.
- Make question points add up exactly to {max_points}.
- Make rubric criterion points add up exactly to {max_points}.
- Avoid ambiguous wording; include any necessary assumptions in directions.
- Do not invent official standards or claim alignment not provided.
- Return no markdown fences or prose outside the JSON object."""


def generate_materials(
    instructions,
    material_type,
    subject,
    grade_level,
    difficulty,
    question_count,
    max_points,
    source_rubric,
    provider,
    model,
):
    """Ask the configured server-side provider to create and validate an assessment."""
    prompt = _generation_prompt(
        instructions,
        material_type,
        subject,
        grade_level,
        difficulty,
        question_count,
        max_points,
        source_rubric,
    )

    if provider == "gemini":
        api_key = os.environ["GEMINI_API_KEY"]
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
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
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:700]
            raise RuntimeError(f"Gemini generation failed ({error.code}): {detail}") from None
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"Gemini could not be reached: {error}") from None
        try:
            response_text = result["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("Gemini returned no assessment materials.") from error
    elif provider == "huggingface":
        from huggingface_hub import InferenceClient

        try:
            response = InferenceClient(
                model=model,
                token=os.environ["HF_TOKEN"],
                timeout=120,
            ).chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=6000,
                temperature=0.3,
            )
            response_text = response.choices[0].message.content
        except Exception as error:
            raise RuntimeError(
                "Hugging Face assessment generation failed. Check your token, model "
                f"access, and provider availability. Details: {error}"
            ) from None
        if isinstance(response_text, list):
            response_text = "\n".join(
                str(part.get("text", ""))
                for part in response_text
                if isinstance(part, dict)
            )
    else:
        raise RuntimeError("Configure Gemini or a compatible Hugging Face chat model to generate materials.")

    if not isinstance(response_text, str) or not response_text.strip():
        raise RuntimeError("The AI provider returned an empty assessment response.")
    return _parse_material_response(response_text, max_points, question_count)


def _font(size, bold=False):
    candidates = (
        [
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
        ]
        if bold else [
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_lines(draw, text, font, max_width):
    words = str(text).split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def render_material_image(title, subtitle, sections):
    """Render printable multipage PNGs from generated content."""
    page_width = 1600
    page_height = 2100
    margin = 115
    max_width = page_width - margin * 2
    title_font = _font(64, bold=True)
    heading_font = _font(37, bold=True)
    body_font = _font(30)
    small_font = _font(24)
    pages = []
    page = Image.new("RGB", (page_width, page_height), "#ffffff")
    draw = ImageDraw.Draw(page)
    y = 110

    def start_page():
        nonlocal page, draw, y
        draw.line((margin, page_height - 100, page_width - margin, page_height - 100),
                  fill="#d9e1e6", width=2)
        draw.text((margin, page_height - 76), "GradePilot · Teacher-created materials",
                  font=small_font, fill="#667789")
        draw.text((page_width - margin - 170, page_height - 76),
                  f"Page {len(pages) + 1}", font=small_font, fill="#667789")
        pages.append(page)
        page = Image.new("RGB", (page_width, page_height), "#ffffff")
        draw = ImageDraw.Draw(page)
        y = 110
        if pages:
            draw.text((margin, y), title, font=heading_font, fill="#172b3c")
            y += 58
            draw.text((margin, y), f"{subtitle} · continued", font=small_font, fill="#617486")
            y += 70
            draw.line((margin, y, page_width - margin, y), fill="#d9e1e6", width=2)
            y += 42

    draw.rounded_rectangle((margin, y, page_width - margin, y + 15), radius=7, fill="#087f79")
    y += 44
    for line in _wrap_lines(draw, title, title_font, max_width):
        draw.text((margin, y), line, font=title_font, fill="#172b3c")
        y += 78
    for line in _wrap_lines(draw, subtitle, small_font, max_width):
        draw.text((margin, y), line, font=small_font, fill="#617486")
        y += 40
    y += 16
    draw.line((margin, y, page_width - margin, y), fill="#d9e1e6", width=2)
    y += 44

    for heading, entries in sections:
        if y > page_height - 220:
            start_page()
        draw.text((margin, y), str(heading), font=heading_font, fill="#087f79")
        y += 58
        for entry in entries:
            lines = _wrap_lines(draw, entry, body_font, max_width - 36)
            estimated_height = len(lines) * 43 + 22
            if y + estimated_height > page_height - 145:
                start_page()
                draw.text((margin, y), f"{heading} · continued", font=heading_font, fill="#087f79")
                y += 58
            draw.rounded_rectangle(
                (margin, y - 4, page_width - margin, y + estimated_height - 8),
                radius=14,
                fill="#f5f8f8",
            )
            text_y = y + 10
            for line in lines:
                draw.text((margin + 18, text_y), line, font=body_font, fill="#26394a")
                text_y += 43
            y += estimated_height + 12
        y += 24

    draw.line((margin, page_height - 100, page_width - margin, page_height - 100),
              fill="#d9e1e6", width=2)
    draw.text((margin, page_height - 76), "GradePilot · Teacher-created materials",
              font=small_font, fill="#667789")
    draw.text((page_width - margin - 170, page_height - 76),
              f"Page {len(pages) + 1}", font=small_font, fill="#667789")
    pages.append(page)

    outputs = []
    for page in pages:
        output = BytesIO()
        page.save(output, format="PNG")
        outputs.append(output.getvalue())
    return outputs


def material_images(material, subject, grade_level, material_type):
    """Create assignment, rubric-only, and answer-key-only printable PNGs."""
    subtitle = f"{subject} · {grade_level} · {material_type}"
    assignment_sections = [
        ("Directions", [material["directions"]]),
        ("Questions", [
            f"{question['number']}. ({question['points']:g} points) {question['prompt']}"
            for question in material["questions"]
        ]),
    ]
    rubric_sections = [
        ("Scoring rubric", [
            f"{item['criterion']} · {item['points']:g} points. {item['description']}"
            for item in material["rubric"]
        ]),
    ]
    answer_sections = [
        ("Answer key", [
            f"{question['number']}. {question['answer']}"
            for question in material["questions"]
        ]),
    ]
    return {
        "assignment": render_material_image(
            material["title"], subtitle, assignment_sections
        ),
        "rubric": render_material_image(
            f"{material['title']} · Rubric", subtitle, rubric_sections
        ),
        "answer_key": render_material_image(
            f"{material['title']} · Answer Key", subtitle, answer_sections
        ),
    }
