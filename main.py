import os
import re
import zipfile
from fastapi import FastAPI, HTTPException
from starlette.responses import Response

# ───────── AYARLAR ─────────
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="ZordoPanelAPI")

# ───────── YARDIMCI FONKSİYONLAR ─────────
def clean_name(name: str) -> str:
    name = name.lower().strip()
    return re.sub(r"[^a-z0-9_]", "", name)

def normalize(text: str) -> str:
    return (
        text.replace(";", "|")
            .replace(",", "|")
            .replace("\t", "|")
    )

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

# ───────── ZIP / DOSYA İŞLEME ─────────
@app.post("/load/{name}")
def load_dataset(name: str):
    """
    data/ klasörüne koyduğun ZIP dosyasını işler.
    Örnek: data/250ksgksorgu.zip
    """
    name = clean_name(name)
    zip_path = os.path.join(DATA_DIR, f"{name}.zip")

    if not os.path.exists(zip_path):
        raise HTTPException(404, "ZIP bulunamadı")

    extract_dir = os.path.join(DATA_DIR, f"unz_{name}")
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)

    files = []
    for root, _, names in os.walk(extract_dir):
        for n in names:
            if n.lower().endswith((".txt", ".csv", ".tsv", ".log")):
                files.append(os.path.join(root, n))

    if not files:
        raise HTTPException(400, "Uygun dosya yok")

    final_txt = os.path.join(DATA_DIR, f"{name}.txt")
    content = combine_files(files)

    with open(final_txt, "w", encoding="utf-8", buffering=32768) as f:
        f.write(content)

    return {
        "status": "ok",
        "api": f"/search/{name}"
    }

# ───────── SORGU API ─────────
@app.get("/search/{dataset}")
def search(dataset: str, q: str = ""):
    dataset = clean_name(dataset)
    path = os.path.join(DATA_DIR, f"{dataset}.txt")

    if not os.path.exists(path):
        raise HTTPException(404, "API bulunamadı")

    q = q.lower().strip()
    results = []

    with open(path, "r", encoding="utf-8", errors="ignore", buffering=32768) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if q in line.lower():
                results.append(line)

    if not results:
        return {"count": 0, "results": []}

    # 🔥 Veri çoksa TXT indir
    if len(results) > 50:
        return Response(
            content="\n".join(results),
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename={dataset}_sonuc.txt"
            }
        )

    return {
        "count": len(results),
        "results": results
    }

# ───────── SAĞLIK KONTROL ─────────
@app.get("/")
def root():
    return {"status": "online"}
