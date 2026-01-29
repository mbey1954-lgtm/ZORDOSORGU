import os
import re
import zipfile
import asyncio
from fastapi import FastAPI, HTTPException
from starlette.responses import Response

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message

# ───────── AYARLAR ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# FastAPI ve Aiogram v3 kurulumu
app = FastAPI(title="ZordoBotAPI_V2")
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# ───────── YARDIMCI FONKSİYONLAR ─────────
def clean_name(name: str) -> str:
    """Dosya adını API dostu hale getirir."""
    name = name.lower().strip()
    return re.sub(r"[^a-z0-9_]", "", name)

def normalize_line(line: str) -> str:
    """Satır içindeki ayraçları temizler."""
    return line.replace(";", "|").replace(",", "|").replace("\t", "|").strip()

# ───────── BOT MANTIĞI ─────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🚀 **Zordo API Bot v2 Aktif!**\n\n"
        "📁 Bir dosya (ZIP, TXT, LOG) göndererek anında API oluşturabilirsin.\n"
        "🔍 Kullanım: `/search/dosya_adi?q=kelime`"
    )

@dp.message(F.document)
async def handle_document(message: Message):
    doc = message.document
    base_name = clean_name(os.path.splitext(doc.file_name)[0])
    file_path = os.path.join(DATA_DIR, f"{base_name}.txt")
    
    # Dosyayı indir
    temp_file = os.path.join(DATA_DIR, f"temp_{doc.file_id}")
    await bot.download(doc, destination=temp_file)
    
    processed_lines = []

    # ZIP Dosyası İşleme
    if doc.file_name.lower().endswith(".zip"):
        with zipfile.ZipFile(temp_file, 'r') as z:
            for name in z.namelist():
                if name.lower().endswith((".txt", ".csv", ".log", ".tsv")):
                    with z.open(name) as f:
                        for line in f:
                            clean_l = normalize_line(line.decode('utf-8', errors='ignore'))
                            if clean_l: processed_lines.append(clean_l)
    # Düz Metin Dosyası İşleme
    else:
        with open(temp_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                clean_l = normalize_line(line)
                if clean_l: processed_lines.append(clean_l)

    # Verileri Kaydet
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(processed_lines))
    
    os.remove(temp_file) # Geçici dosyayı sil
    await message.answer(f"✅ **Hazır!**\nURL: `/search/{base_name}?q=...`")

# ───────── API ENDPOINTLERİ ─────────
@app.get("/")
def home():
    return {"status": "running", "api": "Zordo_V2"}

@app.get("/search/{dataset}")
async def search_api(dataset: str, q: str = ""):
    safe_name = clean_name(dataset)
    db_path = os.path.join(DATA_DIR, f"{safe_name}.txt")
    
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Veriseti bulunamadı.")

    query = q.lower()
    results = []
    
    # Dosyayı satır satır tara (Bellek dostu)
    with open(db_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if query in line.lower():
                results.append(line.strip())
                if len(results) >= 1000: break # Çok büyük sonuçları sınırla

    # Eğer sonuç çoksa dosya olarak indir, azsa JSON döndür
    if len(results) > 50:
        return Response(
            content="\n".join(results),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={safe_name}_results.txt"}
        )
    
    return {"query": q, "total": len(results), "results": results}

# ───────── ÇALIŞTIRMA ─────────
@app.on_event("startup")
async def on_startup():
    if bot:
        asyncio.create_task(dp.start_polling(bot))
