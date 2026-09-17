from fastapi import FastAPI, UploadFile, File
import subprocess
import shutil
import os

app = FastAPI(title="Enterprise Watermark Eradication Engine")

@app.get("/")
def root():
    return {"status": "Engine Running", "mode": "C++ OpenCV Native"}

@app.post("/remove-watermark")
async def remove_watermark(file: UploadFile = File(...)):
    input_path = f"temp_{file.filename}"
    output_path = f"out_{file.filename}"
    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    subprocess.run(["./process_image", input_path, output_path], check=True)
    
    return {"message": "Success", "output": output_path}
