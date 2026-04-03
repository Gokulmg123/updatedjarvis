import asyncio
from random import randint
from PIL import Image
from huggingface_hub import InferenceClient
from dotenv import get_key
import os
from time import sleep

# Load API key same as reference
HuggingFaceAPIKey = get_key('.env', 'HuggingFaceAPIKey')

# ✅ Modern InferenceClient instead of dead requests URL
client = InferenceClient(
    provider="hf-inference",
    api_key=HuggingFaceAPIKey,
)

def open_images(prompt):
    folder_path = r"Data"
    prompt = prompt.replace(" ", "_")
    Files = [f"{prompt}{i}.jpg" for i in range(1, 3)]

    for jpg_file in Files:
        image_path = os.path.join(folder_path, jpg_file)
        try:
            img = Image.open(image_path)
            print(f"Opening image: {image_path}")
            img.show()
            sleep(1)
        except IOError:
            print(f"Unable to open {image_path}")

async def query(prompt: str, index: int):
    """Generate a single image and save it directly."""
    try:
        image = await asyncio.to_thread(
            client.text_to_image,
            prompt=f"{prompt}, quality=4K, sharpness=maximum, Ultra High details, high resolution, seed={randint(0, 1000000)}",
            model="black-forest-labs/FLUX.1-schnell",
        )
        # ✅ Same filename pattern as reference: promptN.jpg
        save_path = rf"Data\{prompt.replace(' ', '_')}{index}.jpg"
        image.save(save_path)
        print(f"Saved: {save_path}")
    except Exception as e:
        print(f"[Image {index} Error]: {e}")

async def generate_images(prompt: str):
    tasks = []
    for i in range(1, 3):   # 1 to 2, same as reference
        task = asyncio.create_task(query(prompt, i))
        tasks.append(task)
    await asyncio.gather(*tasks)

def GenerateImages(prompt: str):
    asyncio.run(generate_images(prompt))
    open_images(prompt)

# ✅ Same main loop, file paths, split logic as reference
while True:
    try:
        with open(r"Frontend\Files\ImageGeneration.data", "r") as f:
            Data: str = f.read()

        Prompt, Status = Data.split(",")

        if Status == "True":
            print("Generating Images ... ")
            GenerateImages(prompt=Prompt)
            with open(r"Frontend\Files\ImageGeneration.data", "w") as f:
                f.write("False,False")
            break
        else:
            sleep(1)
    except:
        pass