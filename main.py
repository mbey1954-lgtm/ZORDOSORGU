import os
import re
import zipfile
import asyncio
from fastapi import FastAPI, HTTPException
from starlette.responses import Response

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

# ───────── AYARLAR ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="ZordoBotAPI_V2")
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# ───────── YARDIMCI ─────────
def clean_name(name: str) -> str:
    name = name.lower().strip()
    return re.sub(r"[^a-z0-9_]", "", name)

def normalize_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    for sep in [";", ",", "\t", "  "]:
        line = line.replace(sep, "|")
    while "||" in line:
        line = line.replace("||", "|")
    return line

def process_and_combine(file_paths):
    out = []
    for p in file_paths:
        try:
            with open(p, "rb") as f:
                for raw in f:
                    line = raw.decode("utf-8", errors="ignore")
                    n = normalize_line(line)
                    if n:
                        out.append(n)
        except:
            continue
    return "\n".join(out)

# ───────── BOT ─────────
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "🚀 Zordo API Aktif\n\n"
        "📂 ZIP / TXT / CSV / TSV / LOG\n"
        "🔗 Otomatik API\n\n"
        "Dosyayı belge olarak gönder."
    )

@dp.message(F.document)
async def handle_document(message: Message):
    doc = message.document
    fname = doc.file_name.lower()

    if not fname.endswith((".zip", ".txt", ".csv", ".tsv", ".log")):
        await message.answer("❌ Desteklenmeyen dosya.")
        return

    base_name = clean_name(os.path.splitext(doc.file_name)[0])
    final_path = os.path.join(DATA_DIR, f"{base_name}.txt")

    status = await message.answer("⚙️ İşleniyor...")

    temp_path = os.path.join(DATA_DIR, f"temp_{doc.file_id}")
    await bot.download(doc, destination=temp_path)

    extracted = []
    unzip_dir = os.path.join(DATA_DIR, f"unzip_{doc.file_id}")

    if fname.endswith(".zip"):
        os.makedirs(unzip_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(temp_path) as z:
                z.extractall(unzip_dir)
            for r, _, fs in os.walk(unzip_dir):
                for f in fs:
                    if f.lower().endswith((".txt", ".csv", ".tsv", ".log")):
                        extracted.append(os.path.join(r, f))
        except:
            await status.edit_text("❌ ZIP açılamadı.")
            return
    else:
        extracted.append(temp_path)

    if not extracted:
        await status.edit_text("❌ Veri bulunamadı.")
        return

    combined = process_and_combine(extracted)
    with open(final_path, "w", encoding="utf-8") as f:
        f.write(combined)

    # Temizlik
    if os.path.exists(temp_path):
        os.remove(temp_path)
    if os.path.exists(unzip_dir):
        for r, d, fs in os.walk(unzip_dir, topdown=False):
            for x in fs: os.remove(os.path.join(r, x))
            for x in d: os.rmdir(os.path.join(r, x))
        os.rmdir(unzip_dir)

    api_link = f"{BASE_URL}/search/{base_name}?q=kelime"
    await status.edit_text(
        f"✅ API Hazır\n\n"
        f"📂 Dataset: `{base_name}`\n"
        f"🔗 {api_link}"
    )

# ───────── API ─────────
@app.get("/")
def home():
    return {"status": "online", "docs": f"{BASE_URL}/docs"}

@app.get("/search/{dataset}")
async def search_api(dataset: str, q: str = ""):
    if not q:
        return {"error": "q parametresi zorunlu"}

    datasets = [clean_name(x) for x in dataset.split(",")]
    query = q.lower().strip()

    results = []

    for ds in datasets:
        path = os.path.join(DATA_DIR, f"{ds}.txt")
        if not os.path.exists(path):
            continue

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if query in line.lower():
                    results.append(f"{ds}|{line.strip()}")
                if len(results) >= 2000:
                    break

    if not results:
        return {
            "datasets": datasets,
            "query": query,
            "total": 0
        }

    if len(results) > 50:
        return Response(
            "\n".join(results),
            media_type="text/plain",
            headers={
                "Content-Disposition":
                f"attachment; filename=sonuc_{query}.txt"
            }
        )

    return {
        "datasets": datasets,
        "query": query,
        "total": len(results),
        "results": results
    }

# ───────── STARTUP ─────────
@app.on_event("startup")
async def startup():
    if bot:
        asyncio.create_task(dp.start_polling(bot))
