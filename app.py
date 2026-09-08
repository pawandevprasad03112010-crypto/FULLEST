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

# ==========================================
# AWS Credentials & Region Settings
# ==========================================
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1").strip()
AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "property-images-estatex-1").strip()

# Bedrock Region (Nova Lite is supported in us-east-1)
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1").strip()

# AWS S3 Client Initialization
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
    config=Config(signature_version='s3v4')
)

# AWS Bedrock Runtime Client Initialization
bedrock_runtime = boto3.client(
    'bedrock-runtime',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=BEDROCK_REGION
)

# ==========================================
# MongoDB Database Setup
# ==========================================
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "estatex_db")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "properties")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]


# ==========================================
# Routes
# ==========================================

@app.route('/')
def home():
    return render_template('index.html', db_name=DB_NAME, collection_name=COLLECTION_NAME)


@app.route('/api/upload-s3', methods=['POST'])
def upload_s3():
    """ Uploads property images directly to AWS S3 Bucket """
    try:
        files = request.files.getlist('images')
        if not files:
            return jsonify({"success": False, "error": "No images provided for S3 upload"}), 400

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
        return jsonify({"success": False, "error": f"S3 Upload Error: {str(e)}"}), 500


@app.route('/api/extract-json', methods=['POST'])
def extract_json():
    """ Reads property screenshots and extracts JSON using Amazon Nova AI based on all business rules """
    try:
        data_images = request.files.getlist('data_images')
        s3_urls_raw = request.form.get('s3_urls', '[]')
        s3_urls = json.loads(s3_urls_raw)

        if not data_images:
            return jsonify({"success": False, "error": "No property detail images provided"}), 400

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

        # Prompt with strict business rules
        prompt_text = f"""
        Extract property details from the provided screenshots into a valid JSON object strictly matching the schema and business rules below.

        EXACT BUSINESS RULES:
        1. User & Contact Info:
           - "user_id": Always "ADMIN".
           - "posted_by_type": Always "ADMIN".
           - "category.purpose": Always "BUY".
           - "category.property_type": Always "RESIDENTIAL".
           - "category.sub_type": If subtype found in image, use it. Otherwise default to "FLAT_APARTMENT".
           - "contact.owner_name": Extract owner name if present in image. Otherwise set "ADMIN".
           - "contact.phone": Extract phone number directly from the image.
           - "contact.owner_type": Always "AGENT".

        2. Title & Description:
           - "title_and_description.title": Extract text highlighted in black or main visible bold title (e.g. property name).
           - "title_and_description.description": Extract the description text written directly below the title.

        3. Location & Address Rules:
           - "location.city": Always "Kolkata".
           - "location.state": Always "West Bengal".
           - "location.locality": Extract locality from image.
           - "location.sub_locality": Set same value as "locality".
           - "location.landmark": Deduce/find landmark based on the locality.
           - "location.pincode": Deduce/find standard Pincode based on the Kolkata locality if not explicitly written.
           - "location.full_address": Construct complete address combining locality, landmark, city, state, pincode. Ensure duplicate entries (e.g., locality and sub_locality) appear only ONCE in full_address.

        4. Specifications & Auto-Calculations:
           - "specifications.bhk_type": Extract BHK type (e.g. "3 BHK").
           - "specifications.bhk_numeric": Extract BHK numeric value (e.g. "3").
           - REAL ESTATE AREA CALCULATION:
             * If ANY ONE of (builtup_sqft, carpet_sqft, super_builtup_sqft) is found in the image:
               Auto-calculate the remaining two using standard real estate ratios:
               - Super Built-up Area = Built-up Area / 0.8 (or Carpet / 0.65)
               - Built-up Area = Super Built-up Area * 0.8
               - Carpet Area = Built-up Area * 0.8
             * Populate all three fields (builtup_sqft, carpet_sqft, super_builtup_sqft) in the final output.
           - Balcony Logic:
             * If balconies count is NOT mentioned in image:
               Check bathroom count:
               - If bathrooms are 1, 2, or 3 -> Set "balconies": "1".
               - If bathrooms are 4 or more -> Set "balconies": "2".
           - "specifications.facing_direction": If missing in image, set "NORTH WEST".
           - "specifications.parking": If missing in image, set "YES".
           - "specifications.ownership_type": Always "FREEHOLD".

        5. Pricing, Amenities & Media:
           - "pricing": Extract price details from image.
           - "amenities": Extract list of amenities present in image.
           - "media.images": Must use this exact array: {json.dumps(s3_urls)}
           - "created_at": If creation date is not in image, set "few years".

        TARGET JSON FORMAT:
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
          "amenities": [],
          "media": {{
            "images": {json.dumps(s3_urls)},
            "ai_short_video_url": "na"
          }},
          "created_at": "few years"
        }}

        Return ONLY a raw JSON string without any markdown backticks or extra text.
        """

        content_items.append({"text": prompt_text})

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

        # Model ID for Nova Lite Cross-Region Inference
        response = bedrock_runtime.invoke_model(
            modelId="us.amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload)
        )

        response_body = json.loads(response.get('body').read())
        raw_text = response_body['output']['message']['content'][0]['text']

        # Clean JSON String
        cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()
        parsed_json = json.loads(cleaned_text)

        return jsonify({"success": True, "data": parsed_json}), 200

    except Exception as e:
        return jsonify({"success": False, "error": f"Extraction Failed: {str(e)}"}), 500


@app.route('/api/submit-to-db', methods=['POST'])
def submit_to_db():
    """ Saves final parsed JSON data directly into MongoDB """
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
        return jsonify({"success": False, "error": f"Database Error: {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
        
