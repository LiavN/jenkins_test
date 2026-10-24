# 🚗 מוסך הבית — מערכת מעקב כשירות רכבים

מערכת אישית (PWA) למעקב אחר אחזקת הרכבים במשק הבית: תיעוד טיפולים, תדלוקים
ובדיקות שמן, לוג פעילות, והתראות לפי דרישות היצרן, מצב הרכב וכשלים נפוצים
מהקהילה. מיועדת ל-2 משתמשים, בעברית (RTL), רצה על Docker.

## יכולות
- **ניהול רכבים** — מזוהים מראש: קיה סלטוס 2023 וטויוטה לנד קרוזר 120 (2006).
- **הזנה מהירה** — תדלוקים / בדיקות שמן / טיפולים, עם לוג פעילות מאוחד לכל רכב.
- **חישוב אוטומטי** — ק״מ נוכחי, ק״מ/חודש, וצריכת דלק נגזרים מהרשומות.
- **פיענוח קבלות סרוקות** — העלאת צילום קבלת מוסך → פיענוח ב-Claude Vision →
  טופס אישור מלא-מראש → יצירת רשומת טיפול עם הסריקה מצורפת.
- **התראות** — 3 מקורות (יצרן / מצב הרכב / כשלי קהילה), בדשבורד ובאימייל.
- **ייבוא CSV** — לייבוא היסטוריה מגיליון קיים (אופציונלי).
- **PWA** — ניתנת להתקנה למסך הבית בטלפון ובאנדרואיד שברכב.

## הרצה מהירה (Docker)
```bash
cp .env.example .env      # ערכו: SECRET_KEY, ANTHROPIC_API_KEY, INITIAL_USERS, SMTP
# חובה: הגדירו SECRET_KEY חזק (האפליקציה מסרבת לעלות עם ברירת המחדל):
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up --build
# פתחו http://localhost:8000  (התחברו עם המשתמש מ-INITIAL_USERS)
```

## הרצה מקומית (פיתוח)
```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## הגדרות (`.env`)
| משתנה | תיאור |
|-------|-------|
| `SECRET_KEY` | מפתח לחתימת עוגיות סשן. **חובה** — האפליקציה מסרבת לעלות עם ברירת המחדל/ריק (אלא אם `DEBUG=true`). |
| `DEBUG` | `true` לפיתוח מקומי בלבד — מרפה את בדיקת ה-SECRET_KEY ואת דרישת ה-HTTPS לעוגייה. ברירת מחדל `false`. |
| `ANTHROPIC_API_KEY` | מפתח ל-Claude Vision לפיענוח קבלות. ריק = פיענוח כבוי, הזנה ידנית בלבד. |
| `VISION_MODEL` | מודל הראייה (ברירת מחדל `claude-opus-4-8`). |
| `INITIAL_USERS` | `שם:אימייל:סיסמה`, מופרד בפסיקים. נוצרים בהפעלה ראשונה. |
| `SMTP_*`, `ALERT_EMAIL_*` | שליחת סיכום התראות במייל. ריק = כבוי. |
| `DATABASE_URL`, `RECEIPTS_DIR` | מיקום ה-SQLite וקבצי הסריקות (על ה-volume). |

## התראות אוטומטיות (cron / Jenkins)
נקודת הקצה `POST /cron/digest` מחשבת מחדש התראות ושולחת סיכום מייל.
ניתן לתזמן:
```bash
curl -X POST http://localhost:8000/cron/digest
```
ה-`jenkinsfile` מריץ את הטסטים ובונה את אימג' ה-Docker.

## אבטחה
- **סיסמאות**: מאוחסנות כ-hash עם bcrypt; כל המסכים דורשים התחברות.
- **`SECRET_KEY`**: חובה — האפליקציה מסרבת לעלות עם ברירת המחדל/ריק (אלא אם `DEBUG=true`).
- **עוגיית סשן**: `HttpOnly`, `SameSite=Lax`, ובפרודקשן גם `Secure` (HTTPS בלבד).
- **כותרות אבטחה**: `Content-Security-Policy`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, ו-HSTS בפרודקשן.
- **הגבלת קצב התחברות**: נעילה זמנית לאחר 5 נסיונות כושלים (חלון 15 דק').
- **החלפת סיסמה**: דרך מסך `חשבון` (`/account`) — החליפו את סיסמת ברירת המחדל מיד.
- **העלאת קבלות**: רק JPG/PNG/WEBP/PDF עד 15MB; מוגשות כהורדה עם `nosniff`.
- **חשיפה**: ה-container מאזין ל-`127.0.0.1` בלבד; הגישה דרך ה-Cloudflare tunnel.
- **CI**: שלב `pip-audit` סורק תלויות אחרי הטסטים.

## טסטים
```bash
python3 -m pytest -q
```

## מבנה
```
app/
  main.py         · FastAPI routes
  models.py       · טבלאות (SQLAlchemy)
  telemetry.py    · חישובי ק״מ/צריכה
  alerts.py       · מנוע התראות
  receipts.py     · פיענוח קבלות (Claude Vision)
  importer.py     · ייבוא CSV
  seed_data.py    · רכבים, לוחות יצרן, כשלי קהילה
  notifications.py· סיכום מייל
  templates/ · static/   · ממשק PWA בעברית
tests/            · pytest
```

> לוחות הטיפול והכשלים המוזנים הם **נקודת פתיחה** — ודאו מול ספר הרכב/המוסך.
