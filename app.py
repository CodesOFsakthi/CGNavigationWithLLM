import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

try:
    from google import genai
    from google.genai import types
except ImportError:  # Keep the app usable until dependencies are installed.
    genai = None
    types = None

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")

PATHS = {
    "PATH_A_SB1_CANTEEN": {
        "label": "Path A",
        "source": "SB1 Main Entrance",
        "destination": "Canteen Entrance",
    },
    "PATH_B_SB1_CANTEEN": {
        "label": "Path B",
        "source": "SB1 Main Entrance",
        "destination": "Canteen Entrance",
    },
}
BLOCKS = {
    "MAINBLOCK": "Main Block",
    "CANTEEN": "Canteen",
    "SB1": "SB1",
    "SB2": "SB2",
    "SB3": "SB3",
    "PARKING": "Parking",
    "TURF": "Turf",
}
STATUSES = {"OPEN", "BLOCKED", "UNDER_CONSTRUCTION"}
ACTIONS = {"UPDATE_PATH_STATUS", "RENAME_BLOCK"}
PASSCODE = "2468"


def normalize_status(value):
    normalized = str(value or "").strip().upper().replace(" ", "_")
    aliases = {"UNDERCONSTRUCTION": "UNDER_CONSTRUCTION", "UNDER-CONSTRUCTION": "UNDER_CONSTRUCTION"}
    return aliases.get(normalized, normalized)


def normalize_path(value):
    normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in {"PATH_A", "A"}:
        return "PATH_A_SB1_CANTEEN"
    if normalized in {"PATH_B", "B"}:
        return "PATH_B_SB1_CANTEEN"
    return normalized


def canonical_block(value):
    text = str(value or "").strip().upper()
    aliases = {"SOUTH BLOCK 1": "SB1", "SOUTH_BLOCK_1": "SB1", "FOOD COURT": "CANTEEN"}
    return aliases.get(text, text)


def deterministic_interpretation(command):
    text = str(command or "").strip()
    lower = text.lower()
    is_unblock = any(term in lower for term in ("unblock", "umblock", "reopen", "open again", "available again"))
    has_path_status = any(term in lower for term in ("block", "close", "construction", "under construction", "unblock", "umblock", "reopen", "open"))
    mentions_sb1 = "sb1" in lower or "south block 1" in lower
    mentions_canteen = "canteen" in lower or "food court" in lower
    path_match = re.search(r"\bpath\s*[- ]?([ab])\b", lower)

    rename_match = re.search(
        r"(?:rename|change the name of|call)\s+(?:the\s+)?(?:block\s+|building\s+)?(sb1|south block 1|canteen|food court)\s+(?:to|as)?\s*([a-z][a-z0-9 ]{1,40})",
        lower,
    )
    if rename_match:
        target = canonical_block(rename_match.group(1))
        new_name = rename_match.group(2).strip(" .")
        return {"action": "RENAME_BLOCK", "target": target, "new_name": new_name.title(), "ai_available": False}

    if has_path_status and (mentions_sb1 or path_match) and (mentions_canteen or path_match):
        path = normalize_path(path_match.group(0)) if path_match else None
        status = "OPEN" if is_unblock else ("UNDER_CONSTRUCTION" if "construction" in lower else "BLOCKED")
        return {
            "action": "UPDATE_PATH_STATUS",
            "source": "SB1 Main Entrance",
            "destination": "Canteen Entrance",
            "path": path,
            "status": status,
            "reason": "Admin update" if is_unblock else ("Construction" if "construction" in lower else "Administrator request"),
            "needs_clarification": path is None,
            "ai_available": False,
        }
    return {"action": "UNSUPPORTED", "message": "Describe a path status change or a block rename.", "ai_available": False}


def gemini_interpretation(command):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or genai is None or types is None:
        result = deterministic_interpretation(command)
        result["used_fallback"] = True
        return result

    client = genai.Client(api_key=api_key)
    schema = {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["UPDATE_PATH_STATUS", "RENAME_BLOCK", "UNSUPPORTED"]},
            "source": {"type": "STRING"},
            "destination": {"type": "STRING"},
            "path": {"type": "STRING"},
            "status": {"type": "STRING"},
            "reason": {"type": "STRING"},
            "target": {"type": "STRING"},
            "new_name": {"type": "STRING"},
            "needs_clarification": {"type": "BOOLEAN"},
            "message": {"type": "STRING"},
        },
        "required": ["action"],
    }
    prompt = f"""Interpret this campus admin command into JSON only. Never invent campus IDs.
Known paths: PATH_A_SB1_CANTEEN and PATH_B_SB1_CANTEEN, both SB1 Main Entrance to Canteen Entrance.
Known blocks: SB1, CANTEEN, SB2, SB3, MAINBLOCK, PARKING, TURF.
Statuses: OPEN, BLOCKED, UNDER_CONSTRUCTION.
Actions: UPDATE_PATH_STATUS or RENAME_BLOCK. Treat 'umblock' as unblock/open. If path is omitted, set needs_clarification true.
Command: {command}"""
    try:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0,
            ),
        )
        result = json.loads(response.text)
        result["ai_available"] = True
        return result
    except Exception:
        result = deterministic_interpretation(command)
        result["used_fallback"] = True
        return result


def validate_action(raw):
    action = str(raw.get("action", "")).strip().upper()
    if action not in ACTIONS:
        return None, "Unsupported action."
    if action == "UPDATE_PATH_STATUS":
        path = normalize_path(raw.get("path"))
        status = normalize_status(raw.get("status"))
        if path not in PATHS:
            if status not in STATUSES:
                status = "BLOCKED"
            return {
                "action": action,
                "source": "SB1 Main Entrance",
                "destination": "Canteen Entrance",
                "path": None,
                "status": status,
                "reason": str(raw.get("reason") or "Administrator request")[:120],
                "needs_clarification": True,
            }, None
        if status not in STATUSES:
            return None, "Choose OPEN, BLOCKED, or UNDER_CONSTRUCTION."
        return {
            "action": action,
            "source": PATHS[path]["source"],
            "destination": PATHS[path]["destination"],
            "path": path,
            "status": status,
            "reason": str(raw.get("reason") or "Administrator request")[:120],
        }, None
    target = canonical_block(raw.get("target"))
    new_name = re.sub(r"\s+", " ", str(raw.get("new_name") or "").strip()).strip()
    if target not in BLOCKS:
        return None, "That campus block is not recognized."
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 &'().-]{1,48}", new_name):
        return None, "Enter a valid display name for the block."
    return {"action": action, "target": target, "current_name": BLOCKS[target], "new_name": new_name}, None


@app.get("/")
def viewer():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/admin")
def admin_page():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/edit")
def edit_page():
    return send_from_directory(BASE_DIR, "index.html")


@app.post("/api/ai/admin-command")
def admin_command():
    payload = request.get_json(silent=True) or {}
    command = payload.get("command", "")
    if not isinstance(command, str) or not command.strip():
        return jsonify({"error": "Enter an admin command."}), 400
    interpreted = gemini_interpretation(command)
    validated, error = validate_action(interpreted)
    if error:
        return jsonify({"valid": False, "error": error, "interpretation": interpreted}), 422
    return jsonify({
        "valid": True,
        "interpretation": validated,
        "ai_available": interpreted.get("ai_available", False),
        "usedFallback": interpreted.get("used_fallback", not interpreted.get("ai_available", False)),
    })


@app.post("/api/admin/apply")
def apply_admin_change():
    payload = request.get_json(silent=True) or {}
    if payload.get("passcode") != PASSCODE:
        return jsonify({"error": "Invalid admin passcode."}), 401
    action, error = validate_action(payload.get("action") or {})
    if error:
        return jsonify({"error": error}), 422
    return jsonify({"success": True, "action": action, "timestamp": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
    )
