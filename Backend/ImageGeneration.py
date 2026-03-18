import asyncio
from random import randint
from PIL import Image
import requests
from dotenv import dotenv_values
import os
from time import sleep

# Load env vars consistently with the rest of the project
env_vars = dotenv_values(".env")
API_KEY = env_vars.get("HuggingFaceAPIKey")

if not API_KEY:
    raise ValueError("HuggingFaceAPIKey not found in .env — add it as: HuggingFaceAPIKey=hf_xxxx")

# Reliable public model that works with a standard HuggingFace read token
API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
headers = {"Authorization": f"Bearer {API_KEY}"}


def open_images(prompt):
    folder_path = r"Data"
    prompt = prompt.replace(" ", "_")
    files = [f"{prompt}{i}.jpg" for i in range(1, 5)]

    for jpg_file in files:
        image_path = os.path.join(folder_path, jpg_file)
        try:
            img = Image.open(image_path)
            print(f"Opening image: {image_path}")
            img.show()
            sleep(1)
        except IOError:
            print(f"Unable to open {image_path}")


async def query(payload):
    response = await asyncio.to_thread(
        requests.post, API_URL, headers=headers, json=payload
    )
    # Check for API errors before returning bytes
    if response.status_code != 200:
        print(f"API Error {response.status_code}: {response.text}")
        return None
    return response.content


async def generate_images(prompt: str):
    tasks = []

    for _ in range(4):
        payload = {
            "inputs": f"{prompt}, quality=4K, sharpness=maximum, Ultra High details, high resolution, seed={randint(0, 1000000)}"
        }
        task = asyncio.create_task(query(payload))
        tasks.append(task)

    image_bytes_list = await asyncio.gather(*tasks)

    saved = 0
    for i, image_bytes in enumerate(image_bytes_list):
        if image_bytes is None:
            print(f"Skipping image {i + 1} due to API error.")
            continue
        save_path = rf"Data\{prompt.replace(' ', '_')}{i + 1}.jpg"
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        saved += 1

    print(f"Saved {saved}/4 images.")


def GenerateImages(prompt: str):
    asyncio.run(generate_images(prompt))
    open_images(prompt)


# Main loop — watches ImageGeneration.data for a trigger
while True:
    try:
        with open(r"Frontend\Files\ImageGeneration.data", "r") as f:
            Data: str = f.read().strip()

        if "," not in Data:
            sleep(1)
            continue

        Prompt, Status = Data.split(",", 1)   # maxsplit=1 so commas in prompt are safe
        Prompt = Prompt.strip()
        Status = Status.strip()

        if Status == "True" and Prompt:
            print(f"Generating Images for: {Prompt}")
            GenerateImages(prompt=Prompt)

            with open(r"Frontend\Files\ImageGeneration.data", "w") as f:
                f.write("False,False")
            break

        else:
            sleep(1)

    except Exception as e:
        print(f"[ImageGeneration Error]: {e}")
        sleep(1)