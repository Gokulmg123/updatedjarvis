import asyncio
import io
import os
import requests
from random import randint
from time import sleep
from PIL import Image
from huggingface_hub import InferenceClient
from dotenv import get_key

# ─────────────────────────────────────────────────────────────────────────────
# PATHS  — all absolute so the script works when launched as a subprocess
#          from ANY working directory (main.py uses cwd=project_root, but
#          this makes the file self-contained regardless).
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))   # Backend/
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)                  # jarvis/
DATA_DIR     = os.path.join(PROJECT_ROOT, "Data")
DATA_FILE    = os.path.join(PROJECT_ROOT, "Frontend", "Files", "ImageGeneration.data")

os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# API KEY
# ─────────────────────────────────────────────────────────────────────────────
HuggingFaceAPIKey = get_key(os.path.join(PROJECT_ROOT, ".env"), "HuggingFaceAPIKey")

# ─────────────────────────────────────────────────────────────────────────────
# HUGGINGFACE CLIENT
# ─────────────────────────────────────────────────────────────────────────────
hf_client = InferenceClient(api_key=HuggingFaceAPIKey)

# ─────────────────────────────────────────────────────────────────────────────
# MODEL LIST  — tried in order; first success wins
# ─────────────────────────────────────────────────────────────────────────────
HF_MODELS = [
    "black-forest-labs/FLUX.1-schnell",          # fastest, usually free
    "stabilityai/stable-diffusion-xl-base-1.0",  # reliable, widely cached
    "runwayml/stable-diffusion-v1-5",            # classic, always available
    "stabilityai/stable-diffusion-2-1",          # another solid backup
    "Lykon/dreamshaper-8",                       # popular community model
]

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def safe_filename(text: str) -> str:
    """Strip characters that are illegal in Windows filenames."""
    for ch in r'/\:*?"<>|':
        text = text.replace(ch, "_")
    return text.replace(" ", "_")


def _save(image: Image.Image, prompt: str, index: int) -> str:
    """Save PIL image to DATA_DIR; return the absolute path."""
    path = os.path.join(DATA_DIR, f"{safe_filename(prompt)}{index}.jpg")
    image.convert("RGB").save(path, "JPEG", quality=95)
    return path


def _open_file(path: str) -> None:
    """Open a file in the Windows default application (Photos, Paint, etc.)."""
    os.startfile(os.path.abspath(path))

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER 1 — HuggingFace  (tries every model in HF_MODELS)
# ─────────────────────────────────────────────────────────────────────────────
def _via_huggingface(prompt: str, index: int):
    """Returns saved path (str) on success, None on failure."""
    enhanced = (
        f"{prompt}, ultra realistic, 4K, highly detailed, "
        f"cinematic lighting, sharp focus, masterpiece"
    )
    for model in HF_MODELS:
        try:
            print(f"  [HF] Image {index} -> {model}")
            img  = hf_client.text_to_image(prompt=enhanced, model=model)
            path = _save(img, prompt, index)
            print(f"  [OK] HuggingFace saved: {path}")
            return path
        except Exception as e:
            print(f"  [WARN] {model} failed: {e}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER 2 — Pollinations AI  (100 % free, no API key, HTTP only)
# ─────────────────────────────────────────────────────────────────────────────
def _via_pollinations(prompt: str, index: int):
    """Returns saved path (str) on success, None on failure."""
    try:
        print(f"  [Pollinations] Image {index}")
        enhanced = (
            f"{prompt}, ultra realistic, 4K, highly detailed, "
            f"cinematic lighting, sharp focus"
        )
        enc  = requests.utils.quote(enhanced)
        seed = randint(0, 999999)
        url  = (
            f"https://image.pollinations.ai/prompt/{enc}"
            f"?width=1024&height=1024&seed={seed}&nologo=true"
        )
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        img  = Image.open(io.BytesIO(resp.content))
        path = _save(img, prompt, index)
        print(f"  [OK] Pollinations saved: {path}")
        return path
    except Exception as e:
        print(f"  [WARN] Pollinations failed: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER 3 — Lexica Aperture  (free web API, no key needed)
# ─────────────────────────────────────────────────────────────────────────────
def _via_lexica(prompt: str, index: int):
    """Returns saved path (str) on success, None on failure."""
    try:
        print(f"  [Lexica] Image {index}")
        params = {"q": prompt, "searchMode": "images", "source": "search"}
        resp   = requests.get("https://lexica.art/api/v1/search",
                              params=params, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("images", [])
        if not results:
            print("  [WARN] Lexica: no results")
            return None
        img_url  = results[0].get("src") or results[0].get("srcSmall")
        img_resp = requests.get(img_url, timeout=60)
        img_resp.raise_for_status()
        img  = Image.open(io.BytesIO(img_resp.content))
        path = _save(img, prompt, index)
        print(f"  [OK] Lexica saved: {path}")
        return path
    except Exception as e:
        print(f"  [WARN] Lexica failed: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# ASYNC PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
async def _generate_one(prompt: str, index: int):
    """Try all providers in sequence; return saved path or None."""
    for provider in (_via_huggingface, _via_pollinations, _via_lexica):
        path = await asyncio.to_thread(provider, prompt, index)
        if path:
            return path
    print(f"  [FAIL] All providers failed for image {index}")
    return None


async def _generate_all(prompt: str):
    """Generate images 1 and 2 concurrently."""
    results = await asyncio.gather(
        _generate_one(prompt, 1),
        _generate_one(prompt, 2),
    )
    return [p for p in results if p]

# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def GenerateImages(prompt: str):
    """Generate 2 images and open them in the default Windows viewer."""
    print(f"\n[ImageGen] Starting generation for: '{prompt}'")
    paths = asyncio.run(_generate_all(prompt))
    print(f"[ImageGen] Generation complete -- {len(paths)} image(s) saved.")

    if not paths:
        print("[ImageGen] [WARN] No images were generated.")
        return

    # Open every saved image in Windows default viewer (Photos / Paint)
    for path in paths:
        try:
            print(f"[ImageGen] Opening: {path}")
            _open_file(path)
            sleep(1)      # small gap so both images open cleanly
        except Exception as e:
            print(f"[ImageGen] Could not open {path}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# CONTROL-FILE LOOP — entry point when launched as subprocess by main.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[ImageGen] Watching: {DATA_FILE}")

    while True:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = f.read().strip()

            if "," not in raw:
                sleep(1)
                continue

            # maxsplit=1 so prompts containing commas don't get mangled
            Prompt, Status = raw.split(",", 1)
            Prompt = Prompt.strip()
            Status = Status.strip()

            if Status == "True" and Prompt:
                GenerateImages(Prompt)

                # ── Reset flag so main.py knows we're done ────────────────
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    f.write("False,False")

                break   # one-shot: exit after generating

            sleep(1)

        except Exception as e:
            print(f"[ImageGen loop error]: {e}")
            sleep(1)