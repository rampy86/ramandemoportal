# Hosting the DataIntelligence Platform for free

Two options. Pick **A** if you only need to click through the portal in a meeting.
Pick **B** if you want the real backend (login → one-time code → JWT, documents stored on the server).

| | A. Static demo | B. Full stack on Render |
|---|---|---|
| What runs | `frontend/index.html` only | FastAPI backend + the same HTML, one URL |
| Password tab | Any email + password | Real password check |
| Email code tab | Any email; code shown on screen | Any email; code emailed (or shown on screen until email is set up) |
| Documents | Sample PDFs; uploads stay in your browser tab | Stored on the server |
| Set-up time | ~2 minutes | ~15 minutes |
| Always awake | Yes | Sleeps after 15 min idle, ~1 min to wake |

### Two ways to sign in
- **Password tab** — email + password, straight in. Seeded logins use `ChangeMe123!`.
- **Email code tab** — type *any* email, get a 6-digit code by email, enter it. A new email automatically gets its own investor account (turn this off with `ALLOW_OTP_SIGNUP=false`). After signing in, **Settings → Password** lets that user set a password for the Password tab.

The HTML picks its mode automatically: served by the backend → **Live**, anywhere else → **Demo**.
The pill under the logo on the sign-in screen shows which one you're in.

---

## A. Static demo (Netlify Drop or GitHub Pages)

### Netlify Drop (easiest)
1. Create a free account at https://app.netlify.com/signup (without an account, a dropped site is temporary).
2. Open https://app.netlify.com/drop.
3. Drag the **`frontend`** folder (the one containing `index.html`) onto the page.
4. You get a URL like `https://random-name-123.netlify.app`. Rename it under **Site configuration → Change site name**.
5. To update later: **Deploys** tab → drag the folder again.

### GitHub Pages (alternative)
1. Create a repository on GitHub and upload `index.html` to its root.
2. **Settings → Pages → Build and deployment → Deploy from a branch → `main` / `/ (root)` → Save**.
3. After a minute the site is at `https://<your-username>.github.io/<repo-name>/`.
   (On the free plan the repository must be public for Pages.)

Sign in on the **Password** tab with any email and password, or on the **Email code** tab with any email — demo mode can't send email, so the code is shown on screen.

---

## B. Full stack on Render (free web service)

### 1. Put the code on GitHub
1. Create a new **private** repository on GitHub (e.g. `dataintelligence-platform`).
2. Upload the whole contents of this folder (`app/`, `frontend/`, `Dockerfile`, `render.yaml`, `requirements.txt`, `seed.py`, …).
   Do **not** upload a `.env` file.
   - Browser only: repository page → **Add file → Upload files** → drag everything in → **Commit**.
   - Or with git: `git init && git add . && git commit -m "DataIntelligence platform" && git branch -M main && git remote add origin https://github.com/<you>/dataintelligence-platform.git && git push -u origin main`

### 2. Deploy with the Blueprint
1. Sign up at https://render.com with your GitHub account (no card needed for the free plan).
2. **New → Blueprint** → connect the `dataintelligence-platform` repository.
3. Render reads `render.yaml` and proposes one free web service, `dataintelligence-platform`.
   It asks for the optional values (`BREVO_API_KEY`, `EMAIL_FROM_ADDRESS`, `DEMO_EXTRA_EMAIL`, `DATABASE_URL`) — leave them **blank** for now.
4. Click **Apply** / **Deploy Blueprint**. The first Docker build takes ~3–6 minutes.
5. Open the URL Render shows (e.g. `https://dataintelligence-platform.onrender.com`).
   - Sign-in pill should read **Live API**.
   - **Password** tab: `rampy007@gmail.com` / `ChangeMe123!`, then **Send code** and enter the 4-digit code.
   - **Email code** tab: enter your own email. Until step 3 is done, the code appears on screen instead of being emailed.
   - API docs: `https://<your-app>.onrender.com/docs`

Every push to `main` redeploys automatically.

### 3. (Optional) Send real OTP emails — Brevo
Render's free tier **blocks outbound SMTP (ports 25/465/587)**, so the Gmail SMTP code can't send from there. The backend can use Brevo's HTTPS email API instead (free plan: 300 emails/day).

1. Sign up at https://www.brevo.com.
2. **Senders, domains & dedicated IPs → Senders → Add a sender** — use an address you control and confirm the verification email.
3. **SMTP & API → API keys → Generate a new API key**. Copy it.
4. In Render → your service → **Environment**, set:
   - `BREVO_API_KEY` = the key
   - `EMAIL_FROM_ADDRESS` = the verified sender address
5. **Save, rebuild and deploy.** On the **Email code** tab enter your own email — the code now arrives by email (check spam the first time; free-mail senders like Gmail often land there).
6. When emails arrive reliably, set `DEMO_SHOW_OTP=false` so the code is no longer shown on screen. That's real MFA.

> The seeded demo account is `rampy007@gmail.com`, so once Brevo is on its sign-in codes arrive in that inbox.

### 4. (Optional) Keep data across restarts — Neon Postgres
Free Render services have an **ephemeral disk**: the SQLite database and uploaded files are wiped whenever the service sleeps, restarts, or redeploys. The demo investors and sample documents are recreated automatically on every start, so the demo always works — only *new uploads* disappear.

To keep users, audit logs, and document records:
1. Sign up at https://neon.tech (free plan) → create a project.
2. Copy the connection string (`postgresql://…neon.tech/neondb?sslmode=require`).
3. In Render → **Environment** → set `DATABASE_URL` to it → save & deploy. The backend converts the URL for its async driver automatically.

Uploaded *files* still live on the ephemeral disk. For durable files, set the `AWS_*` / `S3_BUCKET_NAME` variables (S3 isn't free beyond the AWS trial tier).

### 5. Before a demo
- Open the URL ~1 minute before you present — a sleeping free service needs about a minute to wake.
- Change `DEMO_PASSWORD` in Render's environment if the link will be shared outside your team.

---

## C. (Optional) Frontend on Netlify + API on Render
If you prefer the HTML on Netlify (always awake) and the API on Render:
1. Do B (API) and A (HTML).
2. In Render set `ALLOWED_ORIGINS` to your Netlify URL, e.g. `https://meridian-demo.netlify.app`.
3. Either edit `CONFIG.API_BASE` at the top of the `<script>` in `index.html` to your Render URL and redeploy it, or open the Netlify site with `?api=https://<your-app>.onrender.com` appended.
   While the API wakes up, the sign-in pill shows "Waking up server…".

---

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # optional — defaults work for local demo
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000 (portal) and http://localhost:8000/docs (API).
Gmail SMTP works locally: set `SMTP_USER` + `SMTP_PASSWORD` (a Gmail App Password) in `.env`.

Or with Docker: `docker compose up --build`.

---

## Environment variables (quick reference)
| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | insecure dev key | JWT signing — Render generates one |
| `SEED_DEMO_DATA` | `true` | Create demo investors + sample documents on start |
| `DEMO_PASSWORD` | `ChangeMe123!` | Password for seeded logins |
| `DEMO_EXTRA_EMAIL` | — | Adds your own email as a login |
| `DEMO_SHOW_OTP` | `true` | Return the code to the UI (prototype only) |
| `ALLOW_OTP_SIGNUP` | `true` | Email-code sign-in creates accounts for new emails |
| `EMAIL_PROVIDER` | `auto` | `brevo` / `smtp` / `console` / `auto` |
| `BREVO_API_KEY`, `EMAIL_FROM_ADDRESS` | — | Brevo email delivery |
| `SMTP_USER`, `SMTP_PASSWORD` | — | Gmail SMTP (local / paid hosts) |
| `DATABASE_URL` | SQLite file | Any Postgres URL (Neon, Supabase, RDS) |
| `ALLOWED_ORIGINS` | localhost | CORS — only needed when the HTML is hosted elsewhere |
| `AWS_*`, `S3_BUCKET_NAME` | — | S3 document storage |
