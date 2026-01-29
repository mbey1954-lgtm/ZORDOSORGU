import os
import re
import zipfile
import asyncio
from fastapi import FastAPI, HTTPException
from starlette.responses import Response
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

# ───────── AYARLAR ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN yok")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ───────── FASTAPI ─────────
app = FastAPI(title="ZordoBotAPI")

# ───────── AIROGRAM ─────────
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

def clean_name(name: str) -> str:
    name = name.lower().strip()
    return re.sub(r"[^a-z0-9_]", "", name)

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

# ───────── BOT KOMUT ─────────
@dp.message(CommandStart())
async def start(msg: types.Message):
    await msg.answer(
        "🤖 Bot aktif\n\n"
        "ZIP / TXT / CSV / TSV / LOG gönder\n"
        "Dosya adı = API adı\n\n"
        "Örnek:\n"
        "250ksgksorgu.zip → /search/250ksgksorgu?q=123"
    )

@dp.message()
async def handle_file(msg: types.Message):
    if not msg.document:
        return

    fname = msg.document.file_name.lower()
    base = clean_name(os.path.splitext(msg.document.file_name)[0])
    tmp = os.path.join(DATA_DIR, f"tmp_{msg.document.file_id}")

    await bot.download(msg.document, destination=tmp)

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
        await msg.answer("❌ Desteklenmeyen dosya")
        return

    if not files:
        await msg.answer("❌ Dosya bulunamadı")
        return

    final_txt = os.path.join(DATA_DIR, f"{base}.txt")
    content = combine_files(files)

    with open(final_txt, "w", encoding="utf-8", buffering=32768) as f:
        f.write(content)

    try:
        os.remove(tmp)
        if unzip_dir:
            for r, d, fs in os.walk(unzip_dir, topdown=False):
                for x in fs: os.remove(os.path.join(r, x))
                for x in d: os.rmdir(os.path.join(r, x))
            os.rmdir(unzip_dir)
    except:
        pass

    await msg.answer(f"✅ API hazır\n/search/{base}?q=kelime")

# ───────── API ─────────
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

    if len(results) > 50:
        return Response(
            content="\n".join(results),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={dataset}_sonuc.txt"}
        )

    return {"count": len(results), "results": results}

@app.get("/")
def root():
    return {"status": "online"}

# ───────── BOT BAŞLAT ─────────
@app.on_event("startup")
async def startup():
    asyncio.create_task(dp.start_polling(bot))
