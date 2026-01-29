import os
import re
import zipfile
import asyncio
from fastapi import FastAPI, HTTPException
from starlette.responses import Response

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message

# ───────── AYARLAR (ENV) ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Environment'ta sitenin linkini (https://siten.com gibi) tutar
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="ZordoBotAPI_V2")
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# ───────── YARDIMCI FONKSİYONLAR ─────────
def clean_name(name: str) -> str:
    """Dosya adını API ve URL dostu hale getirir (Türkçe karakter ve özel karakter temizliği)"""
    name = name.lower().strip()
    # Sadece harf, rakam ve alt tire bırakır
    return re.sub(r"[^a-z0-9_]", "", name)

def normalize_line(line: str) -> str:
    """CSV/TSV ayırıcılarını (|) karakterine çevirir ve temizler"""
    return line.replace(";", "|").replace(",", "|").replace("\t", "|").strip()

def process_and_combine(file_paths):
    """Bellek dostu dosya birleştirme ve normalizasyon"""
    out = []
    for p in file_paths:
        try:
            with open(p, "rb") as f:
                content = f.read().decode("utf-8", errors="ignore")
                lines = content.splitlines()
                for line in lines:
                    normalized = normalize_line(line)
                    if normalized:
                        out.append(normalized)
        except:
            continue
    return "\n".join(out)

# ───────── BOT MANTIĞI ─────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🚀 **Zordo API Sistemi Aktif**\n\n"
        "📂 **Kabul Edilenler:** ZIP, TXT, CSV, TSV, LOG\n"
        "🔗 **Özellik:** Sınırsız dosya ve otomatik endpoint.\n\n"
        "**Kullanım:** Belge olarak dosya gönderin, API anında hazır olsun."
    )

@dp.message(F.document)
async def handle_document(message: Message):
    doc = message.document
    fname = doc.file_name.lower()
    
    # Desteklenen dosya kontrolü
    if not fname.endswith((".zip", ".txt", ".csv", ".tsv", ".log")):
        await message.answer("❌ **Hata:** Sadece ZIP, TXT, CSV, TSV veya LOG gönderebilirsin.")
        return

    base_name = clean_name(os.path.splitext(doc.file_name)[0])
    final_path = os.path.join(DATA_DIR, f"{base_name}.txt")
    
    status_msg = await message.answer("⚙️ **İşlem başladı...** Veriler ayıklanıyor ve birleştiriliyor.")
    
    temp_zip_path = os.path.join(DATA_DIR, f"temp_{doc.file_id}")
    await bot.download(doc, destination=temp_zip_path)
    
    extracted_files = []
    unzip_dir = os.path.join(DATA_DIR, f"unzip_{doc.file_id}")

    # ZIP İşleme ve Alt Klasör Tarama
    if fname.endswith(".zip"):
        os.makedirs(unzip_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(temp_zip_path, 'r') as z:
                z.extractall(unzip_dir)
            
            for root, _, names in os.walk(unzip_dir):
                for n in names:
                    if n.lower().endswith((".txt", ".csv", ".log", ".tsv")):
                        extracted_files.append(os.path.join(root, n))
        except:
            await status_msg.edit_text("❌ **Hata:** ZIP dosyası açılamadı.")
            return
    else:
        extracted_files.append(temp_zip_path)

    if not extracted_files:
        await status_msg.edit_text("❌ **Hata:** Uygun metin verisi bulunamadı.")
        return

    # Veri setini oluştur (Stream/Birleştirme)
    combined_data = process_and_combine(extracted_files)
    with open(final_path, "w", encoding="utf-8") as f:
        f.write(combined_data)

    # Temizlik (RAM ve Disk tasarrufu için)
    if os.path.exists(temp_zip_path): os.remove(temp_zip_path)
    if os.path.exists(unzip_dir):
        for r, d, fs in os.walk(unzip_dir, topdown=False):
            for x in fs: os.remove(os.path.join(r, x))
            for x in d: os.rmdir(os.path.join(r, x))
        os.rmdir(unzip_dir)

    # Dinamik Link Oluşturma
    api_link = f"{BASE_URL}/search/{base_name}?q=aranacak_kelime"
    await status_msg.edit_text(
        f"✅ **API Başarıyla Oluşturuldu!**\n\n"
        f"📂 **Dataset:** `{base_name}`\n"
        f"🔗 **API Link:**\n{api_link}"
    )

# ───────── GERÇEK API (HTTP GET) ─────────
@app.get("/")
def home():
    return {"status": "online", "system": "Zordo V2 Core", "docs": f"{BASE_URL}/docs"}

@app.get("/search/{dataset}")
async def search_api(dataset: str, q: str = ""):
    safe_name = clean_name(dataset)
    db_path = os.path.join(DATA_DIR, f"{safe_name}.txt")
    
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="API dataset bulunamadı.")

    query = q.lower().strip()
    if not query:
        return {"error": "Lütfen 'q' parametresi ile arama yapın. Örnek: ?q=admin"}

    results = []
    # Stream/Satır satır okuma (RAM dostu: Büyük dosyalarda çökmez)
    with open(db_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if query in line.lower():
                results.append(line.strip())
                # Render Free RAM limiti için güvenlik sınırı (2000 satır)
                if len(results) >= 2000: break 

    # 50+ Sonuçta TXT olarak indir (Hızlı ve temiz çıktı)
    if len(results) > 50:
        return Response(
            content="\n".join(results),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={safe_name}_sonuclar.txt"}
        )
    
    return {
        "dataset": safe_name,
        "query": query,
        "total": len(results),
        "results": results
    }

# ───────── SİSTEM BAŞLATMA ─────────
@app.on_event("startup")
async def on_startup():
    if bot:
        # Polling başlat
        asyncio.create_task(dp.start_polling(bot))
