# star-wars-character-match-and-portrait-creator-94763-94776

Backend (character_generator_backend) now includes:
- Session management (/session)
- Quiz retrieval (/quiz, /quiz/{id}/questions)
- Answer submission (/answers)
- Match computation (/match/{session_id})
- Selfie upload (/upload/selfie) and portrait generation (/generate/{session_id})
- Result retrieval (/results/{session_id})
- Media serving (/media/uploads/{file}, /media/results/{file})
- Admin CRUD for questions, characters, and quizzes under /admin/* (token via ADMIN_TOKEN env, default dev-admin-token)

Run locally:
1) Install deps: pip install -r character_generator_backend/requirements.txt
2) Start server: uvicorn src.api.main:app --reload --host 0.0.0.0 --port 3001 (from character_generator_backend)
3) API Docs: http://localhost:3001/docs

Env:
- ADMIN_TOKEN (optional; default: dev-admin-token)
- SESSION_SECRET (optional; cookie signing)