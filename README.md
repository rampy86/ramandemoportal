# DataIntelligence — Market & M&A Intelligence Portal

FastAPI backend + single-page frontend (`frontend/index.html`) for the DataIntelligence portal: fund & investor documents, earnings call recordings, transcripts, research reports and M&A intelligence (deal tracker, comparable transactions, regulatory filings). Earnings calls, transcripts, research, deals and filings are illustrative sample content built into the page.
Handles email-based MFA (Brevo API or Gmail SMTP), JWT auth, document storage (local or S3), and audit logging.
The backend serves the portal at `/`, so the whole prototype runs as one web service.

> **Free hosting:** see **[DEPLOY.md](DEPLOY.md)** — static demo on Netlify/GitHub Pages, or full stack on Render's free tier.

---

## Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI + Uvicorn |
| Auth | bcrypt + PyJWT |
| MFA | 6-digit OTP via Gmail SMTP |
| Database | SQLite (dev) / PostgreSQL on AWS RDS (prod) |
| File Storage | Local filesystem (dev) / AWS S3 (prod) |
| Deploy | Docker → AWS ECS Fargate or AWS App Runner |

---

## Local Development

### 1. Clone and set up

```bash
git clone <your-repo>
cd meridian-backend

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY, SMTP_USER, SMTP_PASSWORD
```

#### Gmail App Password setup (required for SMTP)

1. Enable **2-Step Verification** on your Google account
2. Go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create a new App Password → select **Mail** → **Other (custom name)**
4. Copy the 16-character password into `.env` as `SMTP_PASSWORD`

> ⚠️ Use the App Password, NOT your regular Gmail password.

### 3. Seed the database

Happens automatically on startup (`SEED_DEMO_DATA=true`). To run it manually:

```bash
python seed.py
```

Creates sample documents and two demo investor accounts:
- `rampy007@gmail.com` / `ChangeMe123!` (then the 4-digit code from **Send code**)
- `raman.dandona@aithonsolutions.com` / `ChangeMe123!`

### 4. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

Portal: [http://localhost:8000](http://localhost:8000) · API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## API Endpoints

### Authentication — two ways to sign in

```
A) Email + password + 4-digit MFA code (emailed fresh for every sign-in)
POST /api/auth/password-mfa     { "email": "...", "password": "..." }
  ← { "message": "...", "email_masked": "j.***@x.com", "delivery": "email|console", "demo_otp": null }
POST /api/auth/login-password   { "email": "...", "password": "...", "mfa_code": "4821" }
  ← { "access_token": "...", "refresh_token": "...", "expires_in": 3600 }

B) Email one-time code (passwordless; new emails self-register if ALLOW_OTP_SIGNUP=true)
POST /api/auth/request-otp      { "email": "..." }
  ← { "message": "...", "email_masked": "ra***@x.com", "delivery": "email|console", "demo_otp": null }
POST /api/auth/verify-mfa       { "email": "...", "otp_code": "847291" }
  ← tokens (code expires in 10 min, max 5 attempts → 30-min lock, 1 code per 30 s)

Other
POST /api/auth/login            password, then emailed code (2-step MFA, optional)
POST /api/auth/set-password     { "new_password": "..." }   (Bearer token) → 204
POST /api/auth/refresh          { "refresh_token": "..." }
GET  /api/auth/me               (Bearer token) ← profile
POST /api/auth/logout           (Bearer token) → audit log entry
```

### Documents

```
GET  /api/documents
  Header: Authorization: Bearer <access_token>
  Query:  ?category=report&fund_name=PE+Fund+VI
  ← List of documents with presigned S3 download URLs

POST /api/documents/upload
  Header: Authorization: Bearer <access_token>
  Form:   file=<binary>, title=..., category=report, fund_name=...
  ← Uploaded document metadata + download_url

GET  /api/documents/{id}/download
  Header: Authorization: Bearer <access_token>
  → Redirects to presigned S3 URL (or streams local file in dev)
```

---

## Connecting the Frontend

Already done — `frontend/index.html` detects the backend automatically:

- Served by this API (same origin) → **Live mode** (real login, OTP, documents).
- Opened anywhere else → **Demo mode** (sample data, code on screen).
- Hosted separately → set `CONFIG.API_BASE` in the HTML or add `?api=https://your-api` to the URL,
  and add the frontend's origin to `ALLOWED_ORIGINS`.

`POST /api/auth/login` also returns `delivery` (`email`|`console`) and, when `DEMO_SHOW_OTP=true`, `demo_otp`.

---

## AWS Deployment

### Option A — AWS App Runner (simplest, recommended)

1. **Push image to ECR:**
   ```bash
   aws ecr create-repository --repository-name meridian-portal-api
   aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
   docker build -t meridian-portal-api .
   docker tag meridian-portal-api:latest <account>.dkr.ecr.us-east-1.amazonaws.com/meridian-portal-api:latest
   docker push <account>.dkr.ecr.us-east-1.amazonaws.com/meridian-portal-api:latest
   ```

2. **Create App Runner service** in AWS Console:
   - Source: ECR image above
   - Port: `8000`
   - Environment variables: add all keys from `.env.example`
   - Auto-deploy on ECR push: ✓

3. **Set DATABASE_URL** to your RDS PostgreSQL endpoint.

4. **Run seed** (one-time) via App Runner console → "Run command":
   ```bash
   python seed.py
   ```

### Option B — ECS Fargate

1. Create an ECS cluster, task definition (512 CPU / 1024 MB memory minimum).
2. Mount secrets from **AWS Secrets Manager** as environment variables.
3. Put an **Application Load Balancer** in front.
4. Attach an **ACM certificate** for HTTPS.
5. Use **RDS PostgreSQL** (set `DATABASE_URL` to asyncpg connection string).
6. Use **S3 bucket** with private ACL for document storage (set `S3_BUCKET_NAME`).

### S3 Bucket Policy (documents)

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::<account>:role/<ecs-task-role>" },
    "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
    "Resource": "arn:aws:s3:::your-bucket-name/documents/*"
  }]
}
```

### IAM Policy for ECS task role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::your-bucket-name/*"
    }
  ]
}
```

---

## Security Checklist

- [ ] Generate a real `SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`)
- [ ] Change default investor passwords after seeding
- [ ] Use Gmail App Password, not your login password
- [ ] Enable HTTPS (ACM cert on ALB or App Runner handles this automatically)
- [ ] Set `ALLOWED_ORIGINS` to your exact frontend domain
- [ ] Switch `DATABASE_URL` to RDS PostgreSQL (not SQLite) for production
- [ ] Enable S3 bucket versioning and server-side encryption
- [ ] Restrict S3 bucket to private — access only via presigned URLs
- [ ] Review `AuditLog` table regularly for suspicious activity

---

## Project Structure

```
meridian-backend/
├── frontend/
│   └── index.html        ← Complete portal UI (demo + live modes)
├── app/
│   ├── main.py           ← FastAPI app + CORS + lifespan + serves frontend
│   ├── seed_data.py      ← Demo investors + sample PDFs (auto on startup)
│   ├── config.py         ← Pydantic settings (reads .env)
│   ├── database.py       ← Async SQLAlchemy engine + session
│   ├── models.py         ← Investor, OTPCode, Document, AuditLog
│   ├── schemas.py        ← Pydantic request/response models
│   ├── security.py       ← bcrypt, OTP generation, JWT
│   ├── email_service.py  ← Brevo API / Gmail SMTP / console + HTML email template
│   └── routers/
│       ├── auth.py       ← Login, MFA, refresh, profile
│       └── documents.py  ← Upload, list, download (S3)
├── seed.py               ← Run the seed manually
├── render.yaml           ← Render free-tier Blueprint
├── DEPLOY.md             ← Free hosting guide
├── requirements.txt
├── Dockerfile
├── docker-compose.yml    ← Local dev
└── .env.example          ← Copy to .env and fill in secrets
```
