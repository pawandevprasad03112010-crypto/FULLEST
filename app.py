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

# AWS S3 Configuration
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "AKIA32VVAONMXVWBXOPE").strip()
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "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").strip()
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1").strip()
AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "property-images-estatex-1").strip()

# Explicit S3 Client with Signature Version 4 & Virtual Addressing
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
    config=Config(
        signature_version='s3v4',
        s3={'addressing_style': 'virtual'}
    )
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

            # Direct put_object call to prevent signature encoding mismatches
            s3_client.put_object(
                Bucket=AWS_S3_BUCKET_NAME,
                Key=unique_filename,
                Body=file.read(),
                ContentType=file.content_type or 'image/png'
            )

            # Generate Public Object URL
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

        pil_images = []
        for img_file in data_images:
            pil_images.append(Image.open(img_file))

        prompt = f"""
        Extract property details from the provided screenshots into a valid JSON object.
        Include property attributes (title, price, location, description, amenities, features, etc.).
        Also include the field 'images' containing this array of S3 image URLs:
        {json.dumps(s3_urls)}

        Return strictly valid JSON only without markdown code blocks.
        """

        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([prompt, *pil_images])
        
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
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
