# AWS Deep Learning Watermark Eradication Engine

An enterprise-grade Python/PyTorch pipeline utilizing Adaptive Sub-Pixel Alpha Matting, CLAHE Contrast Reconstruction, and Multi-Stage Neural Inpainting to automatically erase watermarks from Cloudinary images.

## Setup & Deployment on AWS EC2
```bash
git clone [https://github.com/YOUR_USERNAME/YOUR_REPO.git](https://github.com/YOUR_USERNAME/YOUR_REPO.git) app
cd app
sudo docker build -t ai-engine .
sudo docker run -d -p 80:80 --name watermark-app ai-engine
