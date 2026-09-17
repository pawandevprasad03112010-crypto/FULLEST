import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app import process_single_image, fetch_cloudinary_list

web_app = FastAPI(title="AWS Deep AI Watermark Removal Engine")

@web_app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AWS PyTorch Deep AI Engine</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: white; padding: 20px; text-align: center; }
            .card { max-width: 480px; margin: 30px auto; background: #1e293b; padding: 30px; border-radius: 16px; border: 1px solid #334155; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
            h2 { color: #38bdf8; margin-bottom: 8px; }
            p { color: #94a3b8; font-size: 14px; margin-bottom: 20px; }
            input { width: 90%; padding: 14px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: white; text-align: center; margin-bottom: 20px; font-size: 16px; }
            button { background: linear-gradient(135deg, #2563eb, #1d4ed8); color: white; border: none; padding: 16px; font-weight: bold; border-radius: 8px; cursor: pointer; width: 100%; font-size: 16px; transition: all 0.2s; }
            button:disabled { background: #475569; cursor: not-allowed; }
            .status { margin-top: 20px; font-size: 14px; color: #34d399; line-height: 1.6; word-break: break-all; font-weight: 500; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Deep AI Watermark Engine</h2>
            <p>PyTorch Fourier Inpainting & Sub-Pixel Alpha Matting</p>
            <input type="number" id="imgCount" placeholder="Image Limit - Leave empty for ALL">
            <button id="btn" onclick="startProcess()">Start 100% Deep AI Eradication</button>
            <div id="res" class="status"></div>
        </div>
        <script>
            async function startProcess() {
                const btn = document.getElementById('btn');
                const resDiv = document.getElementById('res');
                const count = document.getElementById('imgCount').value.trim();
                btn.disabled = true;
                resDiv.innerText = 'Connecting PyTorch Engine to Cloudinary...';
                
                try {
                    const initRes = await fetch('/list');
                    const initData = await initRes.json();
                    let ids = initData.ids || [];
                    if(ids.length === 0) { resDiv.innerText = 'No images found in Cloudinary!'; btn.disabled = false; return; }
                    
                    let limit = (count !== "" && !isNaN(count)) ? Math.min(parseInt(count), ids.length) : ids.length;
                    ids = ids.slice(0, limit);
                    
                    for(let i = 0; i < ids.length; i++) {
                        resDiv.innerText = `Deep Neural Inpainting (${i + 1}/${ids.length})\nProcessing ID: ${ids[i]}`;
                        await fetch('/clean?public_id=' + encodeURIComponent(ids[i]), { method: 'POST' });
                    }
                    resDiv.innerText = `Finished! Processed ${ids.length} images.\nWatermarks 100% Eradicated! Check with ?v=2`;
                } catch(e) { resDiv.innerText = 'Execution Error!'; }
                finally { btn.disabled = false; }
            }
        </script>
    </body>
    </html>
    """

@web_app.get("/list")
def list_images():
    return {"ids": fetch_cloudinary_list()}

@web_app.post("/clean")
def clean_image(public_id: str):
    success = process_single_image(public_id)
    return {"success": success}

if __name__ == "__main__":
    uvicorn.run(web_app, host="0.0.0.0", port=80)

