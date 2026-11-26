# TOSY AI — Automatic AI Starter (No ClamAV)

Dark-themed Flask + SQLite AI chat starter. Website-first; Android can be added later.

## Included
- Email/password signup and login (password hashes, not plaintext)
- SQLite user accounts and persistent chat history
- Automatic AI provider gateway for Gemini, OpenAI and OpenRouter
- Configurable provider priority and automatic fallback when a configured provider fails
- API keys are read by the server from environment variables
- 25-message daily free-tier limit
- Pricing page: Free, Pro Monthly ($4.99), Pro Yearly ($49.99)
- Upload endpoint for TXT, MD, PDF, PNG and JPG (12 MB limit)
- Basic extension and file-format checks, random server-side filenames
- Browser voice recording using MediaRecorder
- Health endpoint and Gunicorn deployment entrypoint

## Important: malware scanning is disabled
ClamAV has been removed completely from this version. Uploads are stored after basic file-format checks, but **they are not malware-scanned and must not be treated as safe**. Only upload files you trust. Do not use uploads for sensitive or production workflows until a malware scanner is added again. The app does not claim uploaded files are virus-free.

Uploaded files are stored in `uploads/`. Document/image extraction and passing file contents to the AI are not implemented yet.

## Automatic AI provider setup
Set one or more API keys in the server environment. TOSY tries providers in `AI_PROVIDER_ORDER` (default: `gemini,openai,openrouter`). If a provider errors or returns an unusable response, TOSY tries the next configured provider.

Suggested environment variables:
- `SECRET_KEY`
- `GEMINI_API_KEY` and optionally `GEMINI_MODEL`
- `OPENAI_API_KEY`, optionally `OPENAI_MODEL` and `OPENAI_BASE_URL`
- `OPENROUTER_API_KEY`, optionally `OPENROUTER_MODEL` and `OPENROUTER_BASE_URL`
- `AI_PROVIDER_ORDER=gemini,openai,openrouter`
- `DATABASE_PATH` (optional)

Each provider may have its own billing, rate limits and terms. Automatic fallback does not mean free usage.

## Local setup with Docker Compose
1. Install Docker Desktop (Windows) or Docker Engine + Compose (Linux).
2. Copy `.env.example` to `.env` and configure `SECRET_KEY` and at least one AI API key.
3. Run `docker compose up --build` from this folder.
4. Open `http://localhost:5000`.

## Run Flask directly
1. Create and activate a Python virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Configure `.env`.
4. Run `python app.py`.

## Deployment notes
Configure persistent storage for the SQLite database and `uploads/`. Use HTTPS, a strong `SECRET_KEY`, regular backups, rate limits and monitoring before production. Malware scanning is not included in this build.

## Implementation status
- Checkout is in setup mode and does not charge anyone.
- Real subscriptions require a payment provider and verified webhooks.
- Files are stored but not malware-scanned, extracted or sent to the AI.
- Voice recording works in the browser; live voice/video calls are not implemented.
- This is a development starter, not a production security certification.

## Interface and error handling
The interface uses a neutral charcoal chat layout. Visitor-facing failures use short, friendly messages; technical details remain in server logs.


### Branding assets
The TOSY AI logo and animated loading indicator are stored in `static/images/`. The logo is used in the navigation, chat sidebar, welcome area and browser favicon. The animated GIF is used by the full-page loading overlay during page navigation and form submission.


## TOSY Intel model routing
- Free accounts use `GEMINI_FREE_MODEL` (default: `gemini-3.8-flash`).
- Active Pro accounts try `GEMINI_PRO_MODEL` first (default: `gemini-3.1-pro-preview`), then fall back to Gemini 3.8 Flash.
- If Gemini attempts fail, configured OpenAI/OpenRouter providers are tried in `AI_PROVIDER_ORDER`.
- Model IDs are configurable because Google can change model availability, preview status, and account eligibility.
- The Pro model is not the previously mentioned "Gemini 4 Argon"; that model ID was not verified in Google's official API model catalogue. This build uses Google's documented Gemini 3.1 Pro Preview model ID instead.
- Pro routing is enforced server-side using the account's database plan and optional `plan_expires_at`.
- **Payments are still disabled.** The checkout endpoint is a placeholder, so this ZIP does not activate paid subscriptions or grant users Pro automatically. A verified payment provider/webhook must be implemented before selling subscriptions.
