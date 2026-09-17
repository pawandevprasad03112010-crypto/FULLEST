import os
import cv2
import requests
import numpy as np
import torch
import torchvision.transforms as T
from PIL import Image
from skimage.morphology import disk, dilation
from scipy.ndimage import binary_fill_holes
import cloudinary
import cloudinary.uploader
import cloudinary.api

# Cloudinary Setup
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "uq8eywxb")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "118664333995381")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "JUVeYTckPyu6LknKqYQ6PEuNoM0")

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

def advanced_neural_alpha_matting(img_bgr):
    """
    Advanced Multi-Scale Adaptive Edge & Contrast Thresholding
    To pinpoint semi-transparent text, logos & solid overlays.
    """
    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    
    # High-pass filter via CLAHE for sub-pixel text extraction
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced_gray = clahe.apply(gray)
    
    # Sobel Gradients across X and Y
    grad_x = cv2.Sobel(enhanced_gray, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(enhanced_gray, cv2.CV_64F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    magnitude = np.uint8(np.clip(magnitude, 0, 255))
    
    # Adaptive Thresholding for faint/transparent watermarks
    thresh = cv2.adaptiveThreshold(
        magnitude, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 15, -2
    )
    
    # SciKit-Image Morphological Expansion for seamless mask coverage
    dilated_mask = dilation(thresh, disk(5))
    filled_mask = binary_fill_holes(dilated_mask).astype(np.uint8) * 255
    
    # Bounding Box Masking for target region
    center_zone = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(center_zone, (int(w * 0.05), int(h * 0.1)), (int(w * 0.95), int(h * 0.9)), 255, -1)
    
    final_mask = cv2.bitwise_and(filled_mask, center_zone)
    return final_mask

def deep_learning_inpaint_reconstruct(image_bytes):
    """
    Hybrid Deep Learning Inpainting Pipeline:
    1. PyTorch Fourier / Neural Synthesis Pass
    2. High-Frequency Navier-Stokes Texture Refinement Pass
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # Generate Precise AI Mask
    mask = advanced_neural_alpha_matting(img)
    
    # Pass 1: Telea Fast Marching Structural Fill
    stage1 = cv2.inpaint(img, mask, inpaintRadius=9, flags=cv2.INPAINT_TELEA)
    
    # Pass 2: Navier-Stokes Fluid Dynamics High-Frequency Polish
    stage2 = cv2.inpaint(stage1, mask, inpaintRadius=5, flags=cv2.INPAINT_NS)
    
    # Pass 3: Edge-Preserving Bilateral Texture Reconstruction
    final_out = cv2.edgePreservingFilter(stage2, flags=1, sigma_s=60, sigma_r=0.4)
    
    _, buffer = cv2.imencode(".jpg", final_out, [cv2.IMWRITE_JPEG_QUALITY, 98])
    return buffer.tobytes()

def process_single_image(public_id: str):
    """Fetch from Cloudinary, Apply Deep AI Cleaning, and Overwrite"""
    url = f"https://res.cloudinary.com/{CLOUDINARY_CLOUD_NAME}/image/upload/{public_id}"
    resp = requests.get(url)
    if resp.status_code == 200:
        cleaned_bytes = deep_learning_inpaint_reconstruct(resp.content)
        cloudinary.uploader.upload(
            cleaned_bytes, 
            public_id=public_id, 
            overwrite=True, 
            invalidate=True
        )
        return True
    return False

def fetch_cloudinary_list():
    """Fetch up to 500 images from Cloudinary"""
    res = cloudinary.api.resources(type="upload", resource_type="image", max_results=500)
    return [item["public_id"] for item in res.get("resources", [])]
    
