import os
import json
from typing import Optional
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from .db import init_db, create_person, list_people, get_person, update_person, delete_person, archive_person, find_existing_person
from .langgraph_flow import run_flow

APP_TITLE = "Search4People"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")
TEMPLATES_DIR = os.path.join(os.path.dirname(BASE_DIR), "templates")
STATIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "static")

# Load env from .env if present
load_dotenv()

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Ensure DB is initialized even when lifespan events are not run (e.g., some test contexts)
try:
    _default_db_path = os.getenv("DB_PATH", os.path.join(DATA_DIR, "search4people.db"))
    init_db(_default_db_path)
except Exception:
    # In server runtime, lifespan will initialize; ignore failures here
    pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.getenv("DB_PATH", os.path.join(DATA_DIR, "search4people.db"))
    init_db(db_path)
    yield

app = FastAPI(title=APP_TITLE, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Markdown filter for Jinja
try:
    import markdown as _md  # type: ignore
    def _md_filter(text: Optional[str]) -> str:
        return _md.markdown(text or "", extensions=["extra"])  # basic markdown -> HTML
except Exception:
    # Ensure a fallback is available if markdown library is missing
    def _md_filter(text: Optional[str]) -> str:
        return text or ""
# Register filter regardless of branch
templates.env.filters["md"] = _md_filter

# In-memory task/status registry
_TASK_STATUS = {}  # person_id -> {"status": str, "message": str}

def _set_status(person_id: int, status: str, message: str = ""):
    _TASK_STATUS[int(person_id)] = {"status": status, "message": message}

def _get_status(person_id: int):
    return _TASK_STATUS.get(int(person_id))

# Background worker to run flow and update DB/status
def _run_flow_bg(person_id: int, inputs: Optional[dict], decision: Optional[str]):
    try:
        prior_state = {}
        if inputs is None:
            row = get_person(person_id)
            if row and row.get("data_json"):
                try:
                    prior_state = json.loads(row["data_json"] or "{}")
                except Exception:
                    prior_state = {}
        state, report_text = run_flow(inputs=inputs, prior_state=prior_state, user_decision=decision)
        update_person(person_id, data_json=json.dumps(state), summary=state.get("summary", None), report_text=report_text)
        if state.get("awaiting_user"):
            _set_status(person_id, "awaiting_user", "Waiting for user confirmation…")
        else:
            _set_status(person_id, "done", "Completed")
    except Exception as e:
        _set_status(person_id, "error", f"{e}")


def _db_awaiting_user(person_id: int) -> bool:
    row = get_person(person_id)
    if not row:
        return False
    try:
        state = json.loads(row.get("data_json") or "{}")
    except Exception:
        state = {}
    return bool(state.get("awaiting_user"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"title": APP_TITLE})


@app.post("/search")
async def start_search(
    request: Request,
    background_tasks: BackgroundTasks,
    first_name: Optional[str] = Form(default=""),
    last_name: Optional[str] = Form(default=""),
    surname: Optional[str] = Form(default=""),
    phone: Optional[str] = Form(default=""),
    photo: Optional[UploadFile] = File(default=None),
):
    # Check for an existing active person that matches provided fields BEFORE saving photo or creating a record
    existing = find_existing_person(first_name=first_name, last_name=last_name, surname=surname, phone=phone)
    if existing:
        # Redirect to existing person's details without creating a duplicate
        return RedirectResponse(url=f"/people/{existing['id']}", status_code=303)

    photo_path = None
    if photo and photo.filename:
        dest = os.path.join(PHOTOS_DIR, photo.filename)
        content = await photo.read()
        with open(dest, "wb") as f:
            f.write(content)
        photo_path = os.path.relpath(dest, os.path.dirname(BASE_DIR))

    person_id = create_person(
        first_name=first_name or "",
        last_name=last_name or "",
        surname=surname or "",
        phone=phone or "",
        photo_path=photo_path,
    )

    # Schedule background processing
    _set_status(person_id, "running", "Searching and preparing candidates…")
    background_tasks.add_task(_run_flow_bg, person_id, {
        "first_name": first_name,
        "last_name": last_name,
        "surname": surname,
        "phone": phone,
    }, None)

    return RedirectResponse(url=f"/people/{person_id}", status_code=303)


@app.get("/people", response_class=HTMLResponse)
def people_list(request: Request):
    rows = list_people()
    return templates.TemplateResponse(request, "people.html", {"rows": rows, "title": APP_TITLE})


@app.get("/people/{person_id}", response_class=HTMLResponse)
def person_details(request: Request, person_id: int):
    row = get_person(person_id)
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    # Pretty-print data_json for the page
    state = {}
    if row.get("data_json"):
        try:
            state = json.loads(row["data_json"]) or {}
        except Exception:
            state = {}
    task = _get_status(person_id) or {}
    # Derive status if not set
    derived_status = task.get("status") if task else None
    if not derived_status:
        if bool(state.get("awaiting_user")):
            derived_status = "awaiting_user"
        elif row.get("report_text") or state.get("report"):
            derived_status = "done"
        else:
            derived_status = "idle"
    return templates.TemplateResponse(
        request,
        "person_details.html",
        {
            "row": row,
            "state": state,
            "task_status": derived_status,
            "title": APP_TITLE,
        },
    )


@app.get("/confirm/{person_id}", response_class=HTMLResponse)
def confirm_match(request: Request, person_id: int):
    row = get_person(person_id)
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    state = {}
    try:
        state = json.loads(row.get("data_json") or "{}")
    except Exception:
        state = {}
    candidates = state.get("candidates", [])
    current_idx = state.get("current_index", 0)
    current_candidate = candidates[current_idx] if candidates and 0 <= current_idx < len(candidates) else None
    return templates.TemplateResponse(
        request,
        "confirm_match.html",
        {
            "row": row,
            "candidate": current_candidate,
            "title": APP_TITLE,
        },
    )


@app.post("/confirm/{person_id}")
def submit_confirmation(person_id: int, decision: str = Form(...), background_tasks: BackgroundTasks = None):
    row = get_person(person_id)
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    # Schedule continuation of the flow in background
    _set_status(person_id, "running", "Processing decision…")
    if background_tasks:
        background_tasks.add_task(_run_flow_bg, person_id, None, decision)
    else:
        # Fallback synchronous if background not provided
        _run_flow_bg(person_id, None, decision)
    return RedirectResponse(url=f"/people/{person_id}", status_code=303)


@app.post("/people/{person_id}/update")
def update_info(person_id: int, background_tasks: BackgroundTasks = None):
    row = get_person(person_id)
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    _set_status(person_id, "running", "Updating information…")
    if background_tasks:
        background_tasks.add_task(_run_flow_bg, person_id, None, "collect")
    else:
        _run_flow_bg(person_id, None, "collect")
    return RedirectResponse(url=f"/people/{person_id}", status_code=303)


@app.post("/people/{person_id}/report")
def generate_report(person_id: int, background_tasks: BackgroundTasks = None):
    row = get_person(person_id)
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    _set_status(person_id, "running", "Generating report…")
    if background_tasks:
        background_tasks.add_task(_run_flow_bg, person_id, None, "report")
    else:
        _run_flow_bg(person_id, None, "report")
    return RedirectResponse(url=f"/people/{person_id}", status_code=303)


@app.post("/people/{person_id}/archive")
def archive(person_id: int):
    archive_person(person_id)
    return RedirectResponse(url="/people", status_code=303)


@app.post("/people/{person_id}/remove")
def remove(person_id: int):
    delete_person(person_id)
    return RedirectResponse(url="/people", status_code=303)


@app.get("/status/{person_id}")
def get_status(person_id: int):
    task = _get_status(person_id) or {"status": "idle", "message": ""}
    # also reflect DB-derived awaiting_user if applicable
    if task.get("status") in ("idle", None):
        if _db_awaiting_user(person_id):
            task = {"status": "awaiting_user", "message": "Waiting for user confirmation…"}
    return task


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.app:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), reload=True)