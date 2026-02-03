import os
import re
import zipfile
import gzip
import shutil
import asyncio
import time
from typing import List
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

# ───────── CONFIG ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BASE_URL = os.environ.get("BASE_URL", "http://localhost").rstrip("/")
DATA_DIR = "data"
TMP_DIR = "tmp"
ADMIN_IDS = [8538972848]  # SENİN TELEGRAM ID'Nİ EKLEDİK

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)

MAX_RESULTS = 2000
TXT_THRESHOLD = 50
MAX_FILE_SIZE_MB = 50

app = FastAPI(title="ZordoAPI_ULTIMATE")
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# ───────── GLOBAL ERROR SHIELD ─────────
class SafetyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            return JSONResponse(
                status_code=200,
                content={
                    "error": "internal_error",
                    "message": "İşlem güvenli şekilde durduruldu",
                    "detail": str(e)
                }
            )
app.add_middleware(SafetyMiddleware)

# ───────── HELPERS ─────────
def clean_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().strip())

def normalize_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    for sep in [";", ",", "\t", "  "]:
        line = line.replace(sep, "|")
    while "||" in line:
        line = line.replace("||", "|")
    return line

def safe_read_and_combine(files: List[str]) -> str:
    output = []
    for path in files:
        try:
            if path.endswith(".gz"):
                with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        n = normalize_line(line)
                        if n:
                            output.append(n)
            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        n = normalize_line(line)
                        if n:
                            output.append(n)
        except:
            continue
    return "\n".join(output)

def safe_cleanup(path: str):
    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
    except:
        pass

# ───────── BOT ─────────
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "🚀 Zordo Ultimate API\n"
        "📂 ZIP / GZ / TXT / CSV / TSV / LOG\n"
        "🧠 Otomatik normalize\n"
        "⚙️ Admin kontrolü\n\n"
        "Dosyayı belge olarak gönder."
    )

@dp.message(F.document)
async def handle_document(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Yetkisiz erişim.")
        return

    try:
        doc = message.document
        if doc.file_size and doc.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            await message.answer("❌ Dosya çok büyük.")
            return
        fname = doc.file_name.lower()
        if not fname.endswith((".zip", ".txt", ".csv", ".tsv", ".log", ".gz")):
            await message.answer("❌ Desteklenmeyen dosya.")
            return

        dataset = clean_name(os.path.splitext(doc.file_name)[0])
        final_path = os.path.join(DATA_DIR, f"{dataset}.txt")
        status = await message.answer("⚙️ İşleniyor...")

        tmp_file = os.path.join(TMP_DIR, f"{doc.file_id}")
        await bot.download(doc, destination=tmp_file)

        files = []

        if fname.endswith(".zip"):
            unzip_dir = os.path.join(TMP_DIR, f"unzip_{doc.file_id}")
            os.makedirs(unzip_dir, exist_ok=True)
            with zipfile.ZipFile(tmp_file) as z:
                z.extractall(unzip_dir)
            for r, _, fs in os.walk(unzip_dir):
                for f in fs:
                    if f.lower().endswith((".txt", ".csv", ".tsv", ".log", ".gz")):
                        files.append(os.path.join(r, f))
            safe_cleanup(unzip_dir)
        else:
            files.append(tmp_file)

        if not files:
            await status.edit_text("❌ Uygun veri yok.")
            safe_cleanup(tmp_file)
            return

        data = safe_read_and_combine(files)
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(data)
        safe_cleanup(tmp_file)

        await status.edit_text(
            f"✅ API Hazır\n\n"
            f"📂 Dataset: `{dataset}`\n"
            f"🔗 Endpoint: {BASE_URL}/search/{dataset}?q=kelime"
        )
    except Exception as e:
        await message.answer(f"❌ Hata güvenli şekilde yakalandı:\n{e}")

@dp.message(Command("sil"))
async def delete_dataset(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Yetkisiz erişim.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Kullanım: /sil dataset_adi")
        return

    dataset = clean_name(args[1])
    path = os.path.join(DATA_DIR, f"{dataset}.txt")
    if os.path.isfile(path):
        os.remove(path)
        await message.answer(f"✅ Dataset silindi: {dataset}")
    else:
        await message.answer(f"❌ Dataset bulunamadı: {dataset}")

# ───────── API ─────────
@app.get("/")
def home():
    return {"status": "online", "system": "Zordo Ultimate", "time": int(time.time())}

@app.get("/search/{dataset}")
async def search(dataset: str, q: str = ""):
    if not q:
        return {"error": "q parametresi zorunlu"}

    datasets = [clean_name(x) for x in dataset.split(",")]
    query = q.lower().strip()
    results = []

    for ds in datasets:
        path = os.path.join(DATA_DIR, f"{ds}.txt")
        if not os.path.isfile(path):
            continue

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if query in line.lower():
                        results.append(f"{ds}|{line.strip()}")
                    if len(results) >= MAX_RESULTS:
                        break
        except:
            continue

    if not results:
        return {"datasets": datasets, "query": query, "total": 0, "message": "Sonuç yok"}

    if len(results) > TXT_THRESHOLD:
        return Response(
            "\n".join(results),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=sonuc_{query}.txt"}
        )

    return {"datasets": datasets, "query": query, "total": len(results), "results": results}

# ───────── STARTUP ─────────
@app.on_event("startup")
async def startup():
    if bot:
        asyncio.create_task(dp.start_polling(bot))

# ───────── RUN RENDER UYUMLU ─────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
