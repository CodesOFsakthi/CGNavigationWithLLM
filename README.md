# NaviQuest+

NaviQuest+ is served by the Flask backend in `app.py`. The existing map, road graph, Dijkstra routing, and browser persistence remain in `index.html`.

## LOCAL DEVELOPMENT

1. Create a virtual environment.
2. Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and set the server-side key:

```text
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Never put `GEMINI_API_KEY` in frontend JavaScript or commit `.env`.

4. Start the app:

```powershell
python app.py
```

Open `http://127.0.0.1:5000/`. Without `GEMINI_API_KEY`, the backend keeps the app usable with deterministic rule-based interpretation and returns a configuration message.

The browser calls relative Flask endpoints such as `/api/ai/admin-command`; it never calls Gemini directly. Demo road status, block names, and update notifications continue to use browser `localStorage`. Render's filesystem is not used as permanent storage.

## RENDER DEPLOYMENT

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
gunicorn app:app
```

Environment Variable:

```text
GEMINI_API_KEY = <my Gemini API key>
```

Optional environment variables are `GEMINI_MODEL` and `PORT`. Gunicorn provides the production server binding; the `PORT` value is also supported by the local `python app.py` entry point.

## Demo Flow

- Viewer: click **Admin**.
- Sign in with admin name `admin` and password `2468`.
- In `/edit`, enter `block path b`, choose Path B, choose Blocked, approve, and enter `2468`.
- Refresh and confirm Path B remains blocked; return to Viewer to see the notification.
- Return to `/edit`, enter `umblock path b`, choose Path B and Open, approve, and enter `2468`.
- Test ambiguity with `block the route from sb1 to canteen`; the assistant asks for Path A or Path B.
- Test construction with `put path b under construction`.
- Test renames with `rename SB1 to South Block 1`, then confirm and enter `2468`.
- Use **Reset Demo Data** to restore original names and open road statuses.

## Security Checks

- `GEMINI_API_KEY` is read only by the Flask backend from the server environment.
- The key is not embedded in `index.html`, frontend JavaScript, GeoJSON, or README content.
- `.env` is ignored by Git.
- Gemini output is validated against predefined actions, path IDs, block IDs, statuses, and display-name rules before confirmation or application.
