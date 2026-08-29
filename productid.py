import io
import json
from PIL import Image
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize the Gemini client
client = genai.Client()


# Define exact output structure using Pydantic
class ProductIdentification(BaseModel):
    brand: str | None = Field(description="Brand name or null if unknown")
    product_name: str = Field(description="Concise description of the product")
    category: str = Field(description="Food or grocery category")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


def preprocess_image(image_bytes: bytes, max_dim: int = 512, quality: int = 70) -> bytes:
    """Resizes and compresses the image crop to minimize payload size and latency."""
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((max_dim, max_dim))

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def identify_cropped_item_fast(crop_bytes: bytes) -> dict:
    # Compress crop to reduce upload overhead
    optimized_bytes = preprocess_image(crop_bytes)

    prompt = "Identify the specific grocery or food item shown in this cropped image."

    # Send request with Pydantic schema enforcement to guarantee valid JSON
    response = client.models.generate_content(
        model="gemini-3.6-flash",  # Update to "gemini-2.5-flash" or "gemini-1.5-flash" as needed
        contents=[
            types.Part.from_bytes(data=optimized_bytes, mime_type="image/jpeg"),
            prompt
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ProductIdentification,  
            temperature=0.0,                        
            max_output_tokens=300                   
        )
    )

    return json.loads(response.text)



if __name__ == "__main__":
    image_path = "images/test-images/images.jpg"

    try:
        with open(image_path, "rb") as image_file:
            crop_bytes = image_file.read()

        print("Processing image and sending request to Gemini...")
        
        result = identify_cropped_item_fast(crop_bytes)

        print("\n--- Model Output ---")
        print(json.dumps(result, indent=2))
        
        print("\n--- Accessing Individual Fields ---")
        print(f"Brand: {result.get('brand')}")
        print(f"Product: {result.get('product_name')}")
        print(f"Category: {result.get('category')}")
        print(f"Confidence: {result.get('confidence')}")

    except FileNotFoundError:
        print(f"Error: Could not find image at path '{image_path}'")
    except Exception as e:
        print(f"An error occurred: {e}")