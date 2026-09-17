from fastapi import FastAPI, UploadFile, File
import subprocess
import shutil
import cloudinary
import cloudinary.uploader

app = FastAPI(title="Enterprise Watermark Eradication Engine")

# Cloudinary Configuration
cloudinary.config(
  cloud_name = "uq8eywxb",
  api_key = "118664333995381",
  api_secret = "JUVeYTckPyu6LknKqYQ6PEuNoM0",
  secure = True
)

@app.get("/")
def root():
    return {"status": "Engine Running", "mode": "C++ OpenCV Native"}

@app.post("/remove-watermark")
async def remove_watermark(file: UploadFile = File(...)):
    input_path = f"temp_{file.filename}"
    output_path = f"out_{file.filename}"
    
    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Process image with OpenCV C++ Engine
    subprocess.run(["./process_image", input_path, output_path], check=True)
    
    # Upload processed image to Cloudinary
    upload_result = cloudinary.uploader.upload(output_path)
    
    return {
        "message": "Success",
        "local_output": output_path,
        "cloudinary_url": upload_result.get("secure_url")
    }
