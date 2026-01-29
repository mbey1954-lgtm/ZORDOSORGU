import os
import re
import zipfile
import json
from fastapi import FastAPI, Request, HTTPException
from starlette.responses import Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ───────── AYARLAR ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = os.environ.get("BASE_URL")

if not BOT_TOKEN or not BASE_URL:
    raise RuntimeError("BOT_TOKEN ve BASE_URL gerekli")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "state.json")
if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, "w") as f:
        json.dump({}, f)

def load_state():
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def clean_name(x: str) -> str:
    x = x.lower().strip()
    return re.sub(r"[^a-z0-9_]", "", x)

def normalize(text: str) -> str:
    return text.replace(";", "|").replace(",", "|").replace("\t", "|")

def combine_files(paths):
    out = []
    for p in paths:
        try:
            with open(p, "rb") as f:
                c = f.read().decode("utf-8", errors="ignore")
                c = normalize(c)
                if c.strip():
                    out.append(c.strip())
        except:
            pass
    return "\n".join(out) + "\n"

# ───────── FASTAPI ─────────
app = FastAPI(title="ZordoBotAPI")

# ───────── TELEGRAM APP ─────────
tg_app = Application.builder().token(BOT_TOKEN).build()

# ───────── BOT KOMUTLARI ─────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot aktif\n\n"
        "ZIP / TXT / CSV / TSV / LOG gönder\n"
        "Dosya adı = API adı\n\n"
        "Örnek:\n"
        "250ksgksorgu.zip → /search/250ksgksorgu?q=123"
    )

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    fname = doc.file_name.lower()
    base = clean_name(os.path.splitext(doc.file_name)[0])

    msg = await update.message.reply_text("📥 İşleniyor...")

    file = await doc.get_file()
    tmp = os.path.join(DATA_DIR, f"tmp_{doc.file_id}")
    await file.download_to_drive(tmp)

    files = []
    unzip_dir = None

    if fname.endswith(".zip"):
        unzip_dir = os.path.join(DATA_DIR, f"unz_{base}")
        os.makedirs(unzip_dir, exist_ok=True)
        with zipfile.ZipFile(tmp, "r") as z:
            z.extractall(unzip_dir)

        for root, _, names in os.walk(unzip_dir):
            for n in names:
                if n.lower().endswith((".txt", ".csv", ".tsv", ".log")):
                    files.append(os.path.join(root, n))

    elif fname.endswith((".txt", ".csv", ".tsv", ".log")):
        files.append(tmp)
    else:
        await msg.edit_text("❌ Desteklenmeyen dosya")
        return

    if not files:
        await msg.edit_text("❌ Dosya bulunamadı")
        return

    final_path = os.path.join(DATA_DIR, f"{base}.txt")
    content = combine_files(files)

    with open(final_path, "w", encoding="utf-8", buffering=32768) as f:
        f.write(content)

    state = load_state()
    state[base] = True
    save_state(state)

    try:
        os.remove(tmp)
        if unzip_dir:
            for r, d, fs in os.walk(unzip_dir, topdown=False):
                for x in fs: os.remove(os.path.join(r, x))
                for x in d: os.rmdir(os.path.join(r, x))
            os.rmdir(unzip_dir)
    except:
        pass

    await msg.edit_text(
        f"✅ API hazır\n\n"
        f"{BASE_URL}/search/{base}?q=kelime"
    )

tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(MessageHandler(filters.Document.ALL, upload))

# ───────── SEARCH API ─────────
@app.get("/search/{dataset}")
def search(dataset: str, q: str = ""):
    dataset = clean_name(dataset)
    path = os.path.join(DATA_DIR, f"{dataset}.txt")

    if not os.path.exists(path):
        raise HTTPException(404, "API yok")

    q = q.lower().strip()
    results = []

    with open(path, "r", encoding="utf-8", errors="ignore", buffering=32768) as f:
        for line in f:
            line = line.strip()
            if line and q in line.lower():
                results.append(line)

    if not results:
        return {"count": 0, "results": []}

    if len(results) > 50:
        return Response(
            content="\n".join(results),
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename={dataset}_sonuc.txt"
            }
        )

    return {"count": len(results), "results": results}

# ───────── WEBHOOK ─────────
@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(f"{BASE_URL}/webhook", drop_pending_updates=True)

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, tg_app.bot)
    if update:
        await tg_app.process_update(update)
    return {"ok": True}

@app.get("/")
def root():
    return {"status": "online"}
