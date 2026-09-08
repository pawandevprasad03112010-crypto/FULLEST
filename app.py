import os
import json
import uuid
import base64
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import boto3
from botocore.config import Config
from pymongo import MongoClient

app = Flask(__name__)
CORS(app)

# AWS S3 & Credentials Configuration
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1").strip()
AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "property-images-estatex-1").strip()

# Bedrock Region
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1").strip()

# AWS S3 Client
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
    config=Config(signature_version='s3v4')
)

# AWS Bedrock Runtime Client
bedrock_runtime = boto3.client(
    'bedrock-runtime',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=BEDROCK_REGION
)

# MongoDB Setup
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "estatex_db")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "properties")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]


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

        content_items = []
        for img_file in data_images:
            img_bytes = img_file.read()
            base64_img = base64.b64encode(img_bytes).decode('utf-8')
            
            mime_type = img_file.content_type or 'image/png'
            format_type = mime_type.split('/')[-1] if '/' in mime_type else 'png'
            if format_type == 'jpg':
                format_type = 'jpeg'

            content_items.append({
                "image": {
                    "format": format_type,
                    "source": {
                        "bytes": base64_img
                    }
                }
            })

        # Detailed Extraction & Business Rules Prompt
        prompt_text = f"""
        Extract property details from the provided screenshots into a valid JSON object matching the exact JSON structure below.

        Strict Rules for Extraction & Calculations:
        1. General & Contact Rules:
           - "user_id": Always "ADMIN".
           - "posted_by_type": Always "ADMIN".
           - "category.purpose": Always "BUY".
           - "category.property_type": Always "RESIDENTIAL".
           - "category.sub_type": Extract from image if found, else default to "FLAT_APARTMENT".
           - "contact.owner_name": Extract from image if present, else default to "ADMIN".
           - "contact.phone": Extract phone number from image.
           - "contact.owner_type": Always "AGENT".

        2. Title & Description Rules:
           - "title_and_description.title": Extract the property name/title highlighted in black or top heading.
           - "title_and_description.description": Extract the description text written directly below the title.

        3. Location Rules:
           - "location.city": Always "Kolkata".
           - "location.state": Always "West Bengal".
           - "location.locality": Extract locality from image.
           - "location.sub_locality": Set same as "locality".
           - "location.landmark": Deduce or estimate landmark based on locality.
           - "location.pincode": Deduce pin code based on Kolkata locality if missing in image.
           - "location.full_address": Construct full address using locality, landmark, city, state, pincode. Ensure duplicate terms like sub_locality are not repeated.

        4. Specifications & Real Estate Area Calculations:
           - "specifications.bhk_type" & "bhk_numeric": Extract BHK value from image.
           - Area Calculations: If ANY one among builtup_sqft, carpet_sqft, or super_builtup_sqft is found in the image:
             * Standard rule: Super Built-up Area = Built-up Area / 0.8; Carpet Area = Built-up Area * 0.8 (or vice versa).
             * Auto-calculate and fill all three area fields (builtup_sqft, carpet_sqft, super_builtup_sqft) dynamically based on standard real estate ratios.
           - Balcony Logic:
             * If balconies are missing in image, check bathrooms count:
             * If bathrooms <= 3, set "balconies": "1".
             * If bathrooms >= 4, set "balconies": "2".
           - "specifications.facing_direction": If missing in image, set "NORTH WEST".
           - "specifications.parking": If missing in image, set "YES".
           - "specifications.ownership_type": Always "FREEHOLD".

        5. Amenities & Media Rules:
           - "amenities": Extract list of amenities present in image (e.g. LIFT, SECURITY, POWER_BACKUP, PARKING).
           - "media.images": Use exact array: {json.dumps(s3_urls)}
           - "created_at": If creation date is missing in image, set "few years".

        Target JSON Schema:
        {{
          "user_id": "ADMIN",
          "posted_by_type": "ADMIN",
          "category": {{
            "purpose": "BUY",
            "property_type": "RESIDENTIAL",
            "sub_type": "FLAT_APARTMENT"
          }},
          "contact": {{
            "owner_name": "ADMIN",
            "phone": "na",
            "owner_type": "AGENT"
          }},
          "title_and_description": {{
            "title": "na",
            "description": "na"
          }},
          "location": {{
            "city": "Kolkata",
            "locality": "na",
            "sub_locality": "na",
            "landmark": "na",
            "pincode": "na",
            "state": "West Bengal",
            "full_address": "na"
          }},
          "pricing": {{
            "price_display": "na",
            "price_numeric": "na",
            "is_negotiable": true
          }},
          "specifications": {{
            "bhk_type": "na",
            "bhk_numeric": "na",
            "builtup_sqft": "na",
            "carpet_sqft": "na",
            "super_builtup_sqft": "na",
            "floor_no": "na",
            "total_floors": "na",
            "bathrooms": "na",
            "balconies": "na",
            "furnishing_status": "na",
            "construction_status": "na",
            "facing_direction": "NORTH WEST",
            "property_age": "na",
            "parking": "YES",
            "ownership_type": "FREEHOLD"
          }},
          "amenities": [
            "LIFT",
            "SECURITY",
            "POWER_BACKUP",
            "PARKING"
          ],
          "media": {{
            "images": {json.dumps(s3_urls)},
            "ai_short_video_url": "na"
          }},
          "created_at": "few years"
        }}

        Return strictly valid JSON only without markdown formatting.
        """

        content_items.append({
            "text": prompt_text
        })

        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": content_items
                }
            ],
            "inferenceConfig": {
                "maxTokens": 2500,
                "temperature": 0.1
            }
        }

        response = bedrock_runtime.invoke_model(
            modelId="us.amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload)
        )

        response_body = json.loads(response.get('body').read())
        raw_text = response_body['output']['message']['content'][0]['text']

        cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()
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
            
