import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from starlette.middleware.sessions import SessionMiddleware

# Simple in-memory stores for demo purposes. In a production system, replace with a real database.
QUIZ_STORE: Dict[str, Dict] = {}
QUESTION_STORE: Dict[str, Dict] = {}
CHARACTER_STORE: Dict[str, Dict] = {}
SESSION_STORE: Dict[str, Dict] = {}
RESULT_STORE: Dict[str, Dict] = {}  # session_id -> result dict that includes selected character and generated image path

# Storage directories
BASE_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "storage")
UPLOADS_DIR = os.path.join(BASE_STORAGE_DIR, "uploads")
RESULTS_DIR = os.path.join(BASE_STORAGE_DIR, "results")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# PUBLIC_INTERFACE
class Choice(BaseModel):
    """Represents a choice for a quiz question."""
    id: str = Field(..., description="Unique identifier for the choice")
    text: str = Field(..., description="Choice text to display")
    # Optional scoring weights by character_id
    weights: Dict[str, float] = Field(default_factory=dict, description="Optional weight mapping to character IDs")


# PUBLIC_INTERFACE
class Question(BaseModel):
    """Represents a quiz question with multiple choices."""
    id: str = Field(..., description="Unique identifier of the question")
    text: str = Field(..., description="The question text")
    choices: List[Choice] = Field(..., description="List of choices for the question")
    order: int = Field(..., description="Ordering index for quiz flow (lower appears earlier)")


# PUBLIC_INTERFACE
class Character(BaseModel):
    """Represents a Star Wars character that a user can match to."""
    id: str = Field(..., description="Unique character identifier")
    name: str = Field(..., description="Character display name")
    description: str = Field(..., description="Character description")
    image_url: Optional[str] = Field(None, description="Optional URL/path for the character's base image asset")
    # Optional vector attributes for scoring rules, e.g., traits
    traits: Dict[str, float] = Field(default_factory=dict, description="Optional trait vector for matching")


# PUBLIC_INTERFACE
class Quiz(BaseModel):
    """Represents a quiz definition with a title, description and question IDs."""
    id: str = Field(..., description="Unique quiz identifier")
    title: str = Field(..., description="Quiz title")
    description: Optional[str] = Field(None, description="Quiz description")
    question_ids: List[str] = Field(default_factory=list, description="Ordered list of question IDs for the quiz")
    created_at: str = Field(default_factory=_now_iso, description="Creation timestamp")
    updated_at: str = Field(default_factory=_now_iso, description="Last update timestamp")


# PUBLIC_INTERFACE
class SessionCreateResponse(BaseModel):
    """Response containing a newly created session id."""
    session_id: str = Field(..., description="Newly created session id")
    expires_at: str = Field(..., description="UTC expiration timestamp")


# PUBLIC_INTERFACE
class SubmitAnswerRequest(BaseModel):
    """Request body to submit an answer for a question."""
    session_id: str = Field(..., description="Session ID")
    quiz_id: str = Field(..., description="Quiz ID")
    question_id: str = Field(..., description="Question ID being answered")
    choice_id: str = Field(..., description="Selected choice ID")


# PUBLIC_INTERFACE
class ScoreResult(BaseModel):
    """Score result per character ID."""
    character_id: str = Field(..., description="Character ID")
    score: float = Field(..., description="Computed score")


# PUBLIC_INTERFACE
class MatchResult(BaseModel):
    """Represents the matching result for a session."""
    session_id: str = Field(..., description="Session ID")
    quiz_id: str = Field(..., description="Quiz ID")
    top_match: Optional[ScoreResult] = Field(None, description="Top matching character result")
    scores: List[ScoreResult] = Field(default_factory=list, description="All scores per character")
    character: Optional[Character] = Field(None, description="Resolved character detail")
    portrait_url: Optional[str] = Field(None, description="Generated portrait image URL for the session result")
    created_at: str = Field(default_factory=_now_iso, description="Creation timestamp")


# PUBLIC_INTERFACE
class AdminAuth(BaseModel):
    """Simple admin authentication payload. For demo only."""
    token: str = Field(..., description="Admin token value")


# PUBLIC_INTERFACE
class QuestionCreate(BaseModel):
    """Payload for creating a new question."""
    text: str = Field(..., description="Question text")
    choices: List[Choice] = Field(..., description="Choices for the question")
    order: int = Field(..., description="Order index")


# PUBLIC_INTERFACE
class QuestionUpdate(BaseModel):
    """Payload for updating an existing question."""
    text: Optional[str] = Field(None, description="Question text")
    choices: Optional[List[Choice]] = Field(None, description="Choices for the question")
    order: Optional[int] = Field(None, description="Order index")


# PUBLIC_INTERFACE
class CharacterCreate(BaseModel):
    """Payload for creating a character."""
    name: str = Field(..., description="Character display name")
    description: str = Field(..., description="Description")
    image_url: Optional[str] = Field(None, description="Image URL/path")
    traits: Dict[str, float] = Field(default_factory=dict, description="Trait weights")


# PUBLIC_INTERFACE
class CharacterUpdate(BaseModel):
    """Payload for updating a character."""
    name: Optional[str] = Field(None, description="Character display name")
    description: Optional[str] = Field(None, description="Description")
    image_url: Optional[str] = Field(None, description="Image URL/path")
    traits: Optional[Dict[str, float]] = Field(None, description="Trait weights")


# PUBLIC_INTERFACE
class QuizCreate(BaseModel):
    """Payload for creating a quiz."""
    title: str = Field(..., description="Quiz title")
    description: Optional[str] = Field(None, description="Quiz description")
    question_ids: List[str] = Field(default_factory=list, description="Ordered question IDs")


# PUBLIC_INTERFACE
class QuizUpdate(BaseModel):
    """Payload for updating a quiz."""
    title: Optional[str] = Field(None, description="Quiz title")
    description: Optional[str] = Field(None, description="Quiz description")
    question_ids: Optional[List[str]] = Field(None, description="Ordered question IDs")


# Admin token for simple auth; pull from env if present
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-admin-token")

app = FastAPI(
    title="Star Wars Character Match & Portrait Creator API",
    description="REST API for quiz flow, character matching, selfie upload and portrait generation, and admin management.",
    version="0.1.0",
    openapi_tags=[
        {"name": "health", "description": "Health and service status"},
        {"name": "quiz", "description": "Public quiz retrieval and flow"},
        {"name": "session", "description": "User session management"},
        {"name": "answers", "description": "Answer submission & scoring"},
        {"name": "media", "description": "Selfie upload and portrait serving"},
        {"name": "results", "description": "Character match results"},
        {"name": "admin", "description": "Admin operations for questions, quizzes, and characters"},
    ],
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Basic cookie session middleware for potential future use
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


def _require_admin(token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden: invalid admin token")


def _get_quiz_or_404(quiz_id: str) -> Dict:
    quiz = QUIZ_STORE.get(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


def _get_question_or_404(question_id: str) -> Dict:
    question = QUESTION_STORE.get(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


def _get_character_or_404(character_id: str) -> Dict:
    character = CHARACTER_STORE.get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


def _get_session_or_404(session_id: str) -> Dict:
    session = SESSION_STORE.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Optional expiration check
    if session.get("expires_at") and datetime.utcnow() > datetime.fromisoformat(session["expires_at"].replace("Z", "")):
        raise HTTPException(status_code=410, detail="Session expired")
    return session


# Seed with an example character and simple question set if empty to make the API immediately usable.
def _seed_demo_data():
    if not CHARACTER_STORE:
        CHARACTER_STORE["vader"] = Character(
            id="vader",
            name="Darth Vader",
            description="A powerful Sith Lord with a tragic past.",
            image_url="/media/characters/vader.png",
            traits={"dark": 0.9, "leader": 0.8, "calm": 0.2},
        ).model_dump()
        CHARACTER_STORE["luke"] = Character(
            id="luke",
            name="Luke Skywalker",
            description="A brave Jedi Knight striving for peace.",
            image_url="/media/characters/luke.png",
            traits={"light": 0.9, "hope": 0.8, "calm": 0.6},
        ).model_dump()
        CHARACTER_STORE["leia"] = Character(
            id="leia",
            name="Princess Leia",
            description="A courageous leader of the Rebel Alliance.",
            image_url="/media/characters/leia.png",
            traits={"leader": 0.9, "light": 0.7, "diplomacy": 0.8},
        ).model_dump()

    if not QUESTION_STORE:
        q1_id = "q1"
        q2_id = "q2"
        QUESTION_STORE[q1_id] = Question(
            id=q1_id,
            text="Pick your ideal weekend activity:",
            order=1,
            choices=[
                Choice(id="c1", text="Meditating and reflecting", weights={"luke": 1.0}),
                Choice(id="c2", text="Strategizing a mission", weights={"leia": 1.0}),
                Choice(id="c3", text="Harnessing the power of the dark side", weights={"vader": 1.0}),
            ],
        ).model_dump()
        QUESTION_STORE[q2_id] = Question(
            id=q2_id,
            text="Choose a guiding principle:",
            order=2,
            choices=[
                Choice(id="c4", text="Hope", weights={"luke": 1.0}),
                Choice(id="c5", text="Order", weights={"vader": 1.0}),
                Choice(id="c6", text="Leadership", weights={"leia": 1.0}),
            ],
        ).model_dump()

    if not QUIZ_STORE:
        quiz_id = "default"
        QUIZ_STORE[quiz_id] = Quiz(
            id=quiz_id,
            title="Which Star Wars Character Are You?",
            description="Answer questions to find your Star Wars alter ego!",
            question_ids=["q1", "q2"],
        ).model_dump()


_seed_demo_data()


@app.get("/", summary="Health Check", tags=["health"])
def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


# PUBLIC_INTERFACE
@app.post("/session", response_model=SessionCreateResponse, summary="Create session", tags=["session"])
def create_session(ttl_minutes: int = Query(default=60, description="Session time-to-live in minutes")):
    """Create a new user session for taking a quiz."""
    session_id = str(uuid.uuid4())
    expires_at = (datetime.utcnow() + timedelta(minutes=max(1, ttl_minutes))).isoformat() + "Z"
    SESSION_STORE[session_id] = {
        "id": session_id,
        "created_at": _now_iso(),
        "expires_at": expires_at,
        "answers": {},  # question_id -> choice_id
        "uploads": [],  # list of uploaded file paths
        "quiz_id": None,
        "scored": False,
    }
    return SessionCreateResponse(session_id=session_id, expires_at=expires_at)


# PUBLIC_INTERFACE
@app.get("/quiz", response_model=List[Quiz], summary="List quizzes", tags=["quiz"])
def list_quizzes():
    """List available quizzes."""
    return [Quiz(**q) for q in QUIZ_STORE.values()]


# PUBLIC_INTERFACE
@app.get("/quiz/{quiz_id}", response_model=Quiz, summary="Get quiz", tags=["quiz"])
def get_quiz(quiz_id: str = Path(..., description="Quiz ID")):
    """Retrieve a quiz by ID."""
    quiz = _get_quiz_or_404(quiz_id)
    return Quiz(**quiz)


# PUBLIC_INTERFACE
@app.get("/quiz/{quiz_id}/questions", response_model=List[Question], summary="Get quiz questions", tags=["quiz"])
def get_quiz_questions(quiz_id: str = Path(..., description="Quiz ID")):
    """Return questions for a given quiz in display order."""
    quiz = _get_quiz_or_404(quiz_id)
    ordered = []
    for qid in quiz["question_ids"]:
        q = _get_question_or_404(qid)
        ordered.append(Question(**q))
    return ordered


# PUBLIC_INTERFACE
@app.post("/answers", response_model=Dict[str, str], summary="Submit answer", tags=["answers"])
def submit_answer(payload: SubmitAnswerRequest):
    """Submit an answer for a question within a session.
    Returns the updated answers mapping for the session."""
    session = _get_session_or_404(payload.session_id)
    _get_quiz_or_404(payload.quiz_id)
    q = _get_question_or_404(payload.question_id)

    # Verify choice
    if payload.choice_id not in [c["id"] for c in q["choices"]]:
        raise HTTPException(status_code=400, detail="Invalid choice for question")

    session["answers"][payload.question_id] = payload.choice_id
    session["quiz_id"] = payload.quiz_id
    session["scored"] = False
    return {"status": "ok", "session_id": payload.session_id}


def _compute_scores(session: Dict) -> List[ScoreResult]:
    """Compute scores for all characters based on chosen answer weights."""
    answers: Dict[str, str] = session.get("answers", {})
    tally: Dict[str, float] = {cid: 0.0 for cid in CHARACTER_STORE.keys()}

    for qid, choice_id in answers.items():
        q = _get_question_or_404(qid)
        # find choice
        choice = next((c for c in q["choices"] if c["id"] == choice_id), None)
        if not choice:
            continue
        weights: Dict[str, float] = choice.get("weights", {})
        for char_id, w in weights.items():
            if char_id in tally:
                tally[char_id] += float(w)

    # Normalize not strictly necessary; produce array
    results = [ScoreResult(character_id=cid, score=score) for cid, score in tally.items()]
    # Sort descending
    results.sort(key=lambda r: r.score, reverse=True)
    return results


# PUBLIC_INTERFACE
@app.post("/match/{session_id}", response_model=MatchResult, summary="Compute character match", tags=["results"])
def compute_match(session_id: str = Path(..., description="Session ID")):
    """Compute the best matching character for the given session based on submitted answers."""
    session = _get_session_or_404(session_id)
    quiz_id = session.get("quiz_id")
    if not quiz_id:
        raise HTTPException(status_code=400, detail="No quiz selected in session")

    scores = _compute_scores(session)
    top = scores[0] if scores else None
    character: Optional[Character] = None
    if top and top.score > 0:
        cdict = _get_character_or_404(top.character_id)
        character = Character(**cdict)

    result = MatchResult(
        session_id=session_id,
        quiz_id=quiz_id,
        top_match=top,
        scores=scores,
        character=character,
        portrait_url=None,
    )

    # Store intermediate result
    RESULT_STORE[session_id] = RESULT_STORE.get(session_id, {})
    RESULT_STORE[session_id]["match"] = result.model_dump()
    session["scored"] = True
    return result


# PUBLIC_INTERFACE
@app.post(
    "/upload/selfie",
    summary="Upload selfie image",
    tags=["media"],
    response_model=Dict[str, str],
)
async def upload_selfie(
    session_id: str = Form(..., description="Session ID"),
    file: UploadFile = File(..., description="Image file (jpeg/png)"),
):
    """Upload a selfie image for the given session. Stores the file and returns a reference path.
    In a real system, you might virus-scan, validate metadata, and push to cloud storage."""
    session = _get_session_or_404(session_id)

    # Validate content type
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    ext = ".jpg" if file.content_type == "image/jpeg" else ".png"
    fname = f"{session_id}_{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(UPLOADS_DIR, fname)

    with open(fpath, "wb") as out:
        chunk = await file.read()
        out.write(chunk)

    # Track upload in session
    rel_path = f"/media/uploads/{fname}"
    session["uploads"].append(rel_path)

    return {"status": "ok", "path": rel_path}


# PUBLIC_INTERFACE
@app.post(
    "/generate/{session_id}",
    summary="Generate portrait mash-up",
    tags=["media"],
    response_model=Dict[str, str],
)
def generate_portrait(session_id: str = Path(..., description="Session ID")):
    """Generate an '80s mall-style portrait mash-up.
    This demo simulates generation by copying the latest uploaded selfie to results folder."""
    session = _get_session_or_404(session_id)
    if not session.get("uploads"):
        raise HTTPException(status_code=400, detail="No selfie uploaded for session")

    # Ensure match exists
    result_data = RESULT_STORE.get(session_id, {}).get("match")
    if not result_data or not result_data.get("top_match"):
        raise HTTPException(status_code=400, detail="No match computed for session")

    # Get last uploaded selfie path
    last_upload_rel = session["uploads"][-1]
    last_upload_name = os.path.basename(last_upload_rel)
    src_path = os.path.join(UPLOADS_DIR, last_upload_name)

    if not os.path.exists(src_path):
        raise HTTPException(status_code=404, detail="Uploaded file not found on server")

    # Simulate generation by copying to results folder with new name
    out_name = f"portrait_{session_id}.png"
    out_path = os.path.join(RESULTS_DIR, out_name)
    # For demo, just copy bytes (no transformation); real implementation would call a model/service
    with open(src_path, "rb") as inp, open(out_path, "wb") as out:
        out.write(inp.read())

    rel_out = f"/media/results/{out_name}"
    RESULT_STORE[session_id] = RESULT_STORE.get(session_id, {})
    RESULT_STORE[session_id]["portrait_url"] = rel_out
    return {"status": "ok", "portrait_url": rel_out}


# PUBLIC_INTERFACE
@app.get(
    "/results/{session_id}",
    response_model=MatchResult,
    summary="Get session result",
    tags=["results"],
)
def get_result(session_id: str = Path(..., description="Session ID")):
    """Get the match scores and (if generated) the portrait URL for a session."""
    _ = _get_session_or_404(session_id)
    res = RESULT_STORE.get(session_id, {})
    match_data = res.get("match")
    portrait_url = res.get("portrait_url")
    if not match_data:
        raise HTTPException(status_code=404, detail="No result for session")
    match = MatchResult(**match_data)
    if portrait_url:
        match.portrait_url = portrait_url
    return match


# PUBLIC_INTERFACE
@app.get(
    "/media/uploads/{filename}",
    summary="Serve uploaded selfie",
    tags=["media"],
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
def serve_upload(filename: str = Path(..., description="Uploaded file name")):
    """Serve an uploaded selfie image by filename."""
    fpath_png = os.path.join(UPLOADS_DIR, filename)
    if not os.path.exists(fpath_png):
        raise HTTPException(status_code=404, detail="File not found")
    # Let FileResponse infer mime
    return FileResponse(fpath_png)


# PUBLIC_INTERFACE
@app.get(
    "/media/results/{filename}",
    summary="Serve generated portrait",
    tags=["media"],
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
def serve_result(filename: str = Path(..., description="Result file name")):
    """Serve a generated portrait image by filename."""
    fpath = os.path.join(RESULTS_DIR, filename)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(fpath)


# ----------------- Admin Endpoints ----------------- #

# PUBLIC_INTERFACE
@app.post("/admin/auth", summary="Authenticate admin (token check)", tags=["admin"])
def admin_auth(body: AdminAuth):
    """Validate the provided admin token."""
    _require_admin(body.token)
    return {"status": "ok"}


# QUESTIONS

# PUBLIC_INTERFACE
@app.get("/admin/questions", response_model=List[Question], summary="List questions", tags=["admin"])
def admin_list_questions(token: str = Query(..., description="Admin token")):
    """List all questions."""
    _require_admin(token)
    return [Question(**q) for q in QUESTION_STORE.values()]


# PUBLIC_INTERFACE
@app.post("/admin/questions", response_model=Question, summary="Create question", tags=["admin"])
def admin_create_question(payload: QuestionCreate, token: str = Query(..., description="Admin token")):
    """Create a new question."""
    _require_admin(token)
    qid = uuid.uuid4().hex
    question = Question(id=qid, text=payload.text, choices=payload.choices, order=payload.order)
    QUESTION_STORE[qid] = question.model_dump()
    return question


# PUBLIC_INTERFACE
@app.put("/admin/questions/{question_id}", response_model=Question, summary="Update question", tags=["admin"])
def admin_update_question(
    question_id: str,
    payload: QuestionUpdate,
    token: str = Query(..., description="Admin token"),
):
    """Update an existing question."""
    _require_admin(token)
    existing = _get_question_or_404(question_id)
    if payload.text is not None:
        existing["text"] = payload.text
    if payload.choices is not None:
        existing["choices"] = [c.model_dump() for c in payload.choices]
    if payload.order is not None:
        existing["order"] = payload.order
    QUESTION_STORE[question_id] = existing
    return Question(**existing)


# PUBLIC_INTERFACE
@app.delete("/admin/questions/{question_id}", summary="Delete question", tags=["admin"])
def admin_delete_question(question_id: str, token: str = Query(..., description="Admin token")):
    """Delete a question. Note: does not remove from quizzes automatically."""
    _require_admin(token)
    if question_id not in QUESTION_STORE:
        raise HTTPException(status_code=404, detail="Question not found")
    del QUESTION_STORE[question_id]
    return {"status": "ok"}


# CHARACTERS

# PUBLIC_INTERFACE
@app.get("/admin/characters", response_model=List[Character], summary="List characters", tags=["admin"])
def admin_list_characters(token: str = Query(..., description="Admin token")):
    """List all characters."""
    _require_admin(token)
    return [Character(**c) for c in CHARACTER_STORE.values()]


# PUBLIC_INTERFACE
@app.post("/admin/characters", response_model=Character, summary="Create character", tags=["admin"])
def admin_create_character(payload: CharacterCreate, token: str = Query(..., description="Admin token")):
    """Create a new character."""
    _require_admin(token)
    cid = uuid.uuid4().hex
    character = Character(
        id=cid,
        name=payload.name,
        description=payload.description,
        image_url=payload.image_url,
        traits=payload.traits,
    )
    CHARACTER_STORE[cid] = character.model_dump()
    return character


# PUBLIC_INTERFACE
@app.put("/admin/characters/{character_id}", response_model=Character, summary="Update character", tags=["admin"])
def admin_update_character(
    character_id: str,
    payload: CharacterUpdate,
    token: str = Query(..., description="Admin token"),
):
    """Update an existing character."""
    _require_admin(token)
    existing = _get_character_or_404(character_id)
    if payload.name is not None:
        existing["name"] = payload.name
    if payload.description is not None:
        existing["description"] = payload.description
    if payload.image_url is not None:
        existing["image_url"] = payload.image_url
    if payload.traits is not None:
        existing["traits"] = payload.traits
    CHARACTER_STORE[character_id] = existing
    return Character(**existing)


# PUBLIC_INTERFACE
@app.delete("/admin/characters/{character_id}", summary="Delete character", tags=["admin"])
def admin_delete_character(character_id: str, token: str = Query(..., description="Admin token")):
    """Delete a character."""
    _require_admin(token)
    if character_id not in CHARACTER_STORE:
        raise HTTPException(status_code=404, detail="Character not found")
    del CHARACTER_STORE[character_id]
    return {"status": "ok"}


# QUIZZES

# PUBLIC_INTERFACE
@app.get("/admin/quizzes", response_model=List[Quiz], summary="List quizzes", tags=["admin"])
def admin_list_quizzes(token: str = Query(..., description="Admin token")):
    """List all quizzes."""
    _require_admin(token)
    return [Quiz(**q) for q in QUIZ_STORE.values()]


# PUBLIC_INTERFACE
@app.post("/admin/quizzes", response_model=Quiz, summary="Create quiz", tags=["admin"])
def admin_create_quiz(payload: QuizCreate, token: str = Query(..., description="Admin token")):
    """Create a new quiz."""
    _require_admin(token)
    qz_id = uuid.uuid4().hex
    quiz = Quiz(
        id=qz_id,
        title=payload.title,
        description=payload.description,
        question_ids=payload.question_ids,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    QUIZ_STORE[qz_id] = quiz.model_dump()
    return quiz


# PUBLIC_INTERFACE
@app.put("/admin/quizzes/{quiz_id}", response_model=Quiz, summary="Update quiz", tags=["admin"])
def admin_update_quiz(
    quiz_id: str,
    payload: QuizUpdate,
    token: str = Query(..., description="Admin token"),
):
    """Update an existing quiz."""
    _require_admin(token)
    existing = _get_quiz_or_404(quiz_id)
    if payload.title is not None:
        existing["title"] = payload.title
    if payload.description is not None:
        existing["description"] = payload.description
    if payload.question_ids is not None:
        existing["question_ids"] = payload.question_ids
    existing["updated_at"] = _now_iso()
    QUIZ_STORE[quiz_id] = existing
    return Quiz(**existing)


# PUBLIC_INTERFACE
@app.delete("/admin/quizzes/{quiz_id}", summary="Delete quiz", tags=["admin"])
def admin_delete_quiz(quiz_id: str, token: str = Query(..., description="Admin token")):
    """Delete a quiz."""
    _require_admin(token)
    if quiz_id not in QUIZ_STORE:
        raise HTTPException(status_code=404, detail="Quiz not found")
    del QUIZ_STORE[quiz_id]
    return {"status": "ok"}


# PUBLIC_INTERFACE
@app.get("/docs/websocket-usage", summary="WebSocket usage help", tags=["health"])
def websocket_usage_note():
    """Usage note endpoint. This project currently exposes only REST endpoints; reserved for future websocket additions."""
    return JSONResponse(
        {
            "message": "No WebSocket endpoints are currently exposed. This endpoint is reserved for future real-time features."
        }
    )
