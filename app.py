import os
import json
import uuid
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import boto3
from botocore.config import Config
from pymongo import MongoClient
import google.generativeai as genai
from PIL import Image

app = Flask(__name__)
CORS(app)

# Fetch strictly from Render Environment Variables (strip extra whitespaces)
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1").strip()
AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "property-images-estatex-1").strip()

# Explicit S3 Client configuration using Signature Version 4
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
    config=Config(signature_version='s3v4')
)

# MongoDB Setup
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "estatex_db")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "properties")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]

# Gemini AI Setup
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY.strip())

# Exhaustive Fallback List covering Pro, Flash, Ultra, Lite across all series (3.6, 3.0, 2.5, 2.0, 1.5, 1.0)
ALL_GEMINI_FALLBACK_MODELS = [
    # 3.6 & 3.x Series
    'gemini-3.6-pro',
    'gemini-3.6-flash',
    'gemini-3.0-pro',
    'gemini-3.0-flash',
    'gemini-3-pro',
    'gemini-3-flash',

    # 2.5 Series
    'gemini-2.5-pro',
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',

    # 2.0 Series
    'gemini-2.0-flash',
    'gemini-2.0-pro-exp',
    'gemini-2.0-flash-lite',
    'gemini-2.0-flash-thinking-exp',

    # 1.5 Series
    'gemini-1.5-pro',
    'gemini-1.5-flash',
    'gemini-1.5-flash-8b',

    # 1.0 Series
    'gemini-1.0-pro',
    'gemini-1.0-ultra',
    'gemini-pro',
    'gemini-pro-vision'
]


def get_all_target_models():
    """Fetches live API models first, then merges with explicit fallback list"""
    model_list = []
    
    # 1. Fetch active models from API
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                clean_name = m.name.replace('models/', '')
                model_list.append(clean_name)
    except Exception:
        pass

    # 2. Append explicit hardcoded models ensuring no duplicates
    for target in ALL_GEMINI_FALLBACK_MODELS:
        if target not in model_list:
            model_list.append(target)

    return model_list


@app.route('/')
def home():
    return render_template('index.html', db_name=DB_NAME, collection_name=COLLECTION_NAME)


@app.route('/api/upload-s3', methods=['POST'])
def upload_s3():
    try:
        files = request.files.getlist('images')
        if not files:
            return jsonify({"success": False, "error": "No images provided"}), 400

        uploaded_urls = []
        for file in files:
            file_extension = os.path.splitext(file.filename)[1] or ".png"
            unique_filename = f"property-images/{uuid.uuid4().hex}{file_extension}"

            s3_client.put_object(
                Bucket=AWS_S3_BUCKET_NAME,
                Key=unique_filename,
                Body=file.read(),
                ContentType=file.content_type or 'image/png'
            )

            public_url = f"https://{AWS_S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{unique_filename}"
            uploaded_urls.append(public_url)

        return jsonify({"success": True, "urls": uploaded_urls}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/extract-json', methods=['POST'])
def extract_json():
    try:
        data_images = request.files.getlist('data_images')
        s3_urls_raw = request.form.get('s3_urls', '[]')
        s3_urls = json.loads(s3_urls_raw)

        if not data_images:
            return jsonify({"success": False, "error": "No raw detail images provided"}), 400

        pil_images = [Image.open(img_file) for img_file in data_images]

        prompt = f"""
        Extract property details from the provided screenshots into a valid JSON object.
        Include property attributes (title, price, location, description, amenities, features, etc.).
        Also include the field 'images' containing this array of S3 image URLs:
        {json.dumps(s3_urls)}
        """

        response_text = None
        last_error = None

        candidate_models = get_all_target_models()

        # Iterate through every model until one succeeds
        for model_name in candidate_models:
            try:
                # Try with structured JSON output first
                model = genai.GenerativeModel(
                    model_name,
                    generation_config={"response_mime_type": "application/json"}
                )
                response = model.generate_content([prompt, *pil_images])
                if response and response.text:
                    response_text = response.text
                    break
            except Exception as model_err:
                # Fallback to standard request without response_mime_type if model doesn't support it
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content([prompt, *pil_images])
                    if response and response.text:
                        response_text = response.text
                        break
                except Exception as inner_err:
                    last_error = f"[{model_name}]: {str(inner_err)}"
                    continue

        if not response_text:
            return jsonify({
                "success": False,
                "error": f"All specified Gemini models failed. Last Error: {last_error}"
            }), 500

        cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
        parsed_json = json.loads(cleaned_text)

        return jsonify({"success": True, "data": parsed_json}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/submit-to-db', methods=['POST'])
def submit_to_db():
    try:
        body = request.get_json()
        raw_json_str = body.get('json_data', '')

        if not raw_json_str:
            return jsonify({"success": False, "error": "JSON data is required"}), 400

        parsed_data = json.loads(raw_json_str)

        if isinstance(parsed_data, list):
            result = collection.insert_many(parsed_data)
            inserted_count = len(result.inserted_ids)
            msg = f"{inserted_count} documents inserted successfully!"
        else:
            result = collection.insert_one(parsed_data)
            msg = f"Document inserted successfully with ID: {str(result.inserted_id)}"

        return jsonify({"success": True, "message": msg}), 200

    except json.JSONDecodeError as e:
        return jsonify({"success": False, "error": f"Invalid JSON Format: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
    
