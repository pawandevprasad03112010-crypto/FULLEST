import os
import json
import time
import io
from flask import Flask, request, Response, render_template, jsonify
from flask_cors import CORS
from PIL import Image
import cloudinary
import cloudinary.uploader
from pymongo import MongoClient
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app)

app.json.sort_keys = False

# Cloudinary Config
cloudinary.config(
  cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME"),
  api_key = os.environ.get("CLOUDINARY_API_KEY"),
  api_secret = os.environ.get("CLOUDINARY_API_SECRET")
)

# MongoDB Config
MONGO_URI = os.environ.get("MONGO_URI", "")
DB_NAME = "BUY_PROPERTY_KOLKATA"
COLLECTION_NAME = "KOLKATA_LISTING"

def get_mongo_collection():
    if not MONGO_URI or ("cluster.mongodb.net" in MONGO_URI and "username" in MONGO_URI):
        raise Exception("MONGO_URI environment variable properly set nahi hai Render par!")
    client = MongoClient(MONGO_URI)
    return client[DB_NAME][COLLECTION_NAME]

API_KEY = os.environ.get("GEMINI_API_KEY")

DEFAULT_AMENITIES = ["LIFT", "SECURITY", "POWER_BACKUP", "PARKING"]

def get_default_structure():
    return {
        "user_id": "ADMIN",
        "posted_by_type": "ADMIN",
        "category": {
            "purpose": "BUY",
            "property_type": "RESIDENTIAL",
            "sub_type": "FLAT_APARTMENT"
        },
        "contact": {
            "owner_name": "ADMIN",
            "phone": "na",
            "owner_type": "AGENT"
        },
        "title_and_description": {
            "title": "na",
            "description": "na"
        },
        "location": {
            "city": "Kolkata",
            "locality": "na",
            "sub_locality": "na",
            "landmark": "na",
            "pincode": "na",
            "state": "West Bengal",
            "full_address": "na"
        },
        "pricing": {
            "price_display": "na",
            "price_numeric": "na",
            "is_negotiable": True
        },
        "specifications": {
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
            "construction_status": "READY_TO_MOVE",
            "facing_direction": "NORTH WEST",
            "property_age": "na",
            "parking": "YES",
            "ownership_type": "FREEHOLD"
        },
        "amenities": DEFAULT_AMENITIES,
        "media": {
            "images": [],
            "ai_short_video_url": ""
        },
        "created_at": "few years"
    }

def apply_custom_logic(data, uploaded_urls):
    specs = data.get("specifications", {})

    def to_float(val):
        if val is None or str(val).strip().lower() in ["na", "", "none", "null"]:
            return None
        try:
            clean_str = "".join([c for c in str(val) if c.isdigit() or c == '.'])
            return float(clean_str) if clean_str else None
        except (ValueError, TypeError):
            return None

    def to_int(val):
        try: return int(str(val).strip())
        except (ValueError, TypeError): return None

    carpet = to_float(specs.get("carpet_sqft"))
    builtup = to_float(specs.get("builtup_sqft"))
    super_builtup = to_float(specs.get("super_builtup_sqft"))

    if super_builtup and not builtup and not carpet:
        builtup = round(super_builtup / 1.25, 2)
        carpet = round(builtup / 1.20, 2)
    elif builtup and not super_builtup and not carpet:
        super_builtup = round(builtup * 1.25, 2)
        carpet = round(builtup / 1.20, 2)
    elif carpet and not builtup and not super_builtup:
        builtup = round(carpet * 1.20, 2)
        super_builtup = round(builtup * 1.25, 2)
    elif carpet and super_builtup and not builtup:
        builtup = round(carpet * 1.20, 2)
    elif builtup and super_builtup and not carpet:
        carpet = round(builtup / 1.20, 2)

    specs["carpet_sqft"] = carpet if carpet is not None else "na"
    specs["builtup_sqft"] = builtup if builtup is not None else "na"
    specs["super_builtup_sqft"] = super_builtup if super_builtup is not None else "na"

    const_status = str(specs.get("construction_status", "")).strip().upper()
    if "UNDER" in const_status or "CONSTRUCTION" in const_status:
        specs["construction_status"] = "UNDER_CONSTRUCTION"
    elif not const_status or const_status.lower() in ["na", "none", "null"]:
        specs["construction_status"] = "READY_TO_MOVE"

    bathrooms = to_int(specs.get("bathrooms"))
    balconies = to_int(specs.get("balconies"))
    if balconies is None or str(balconies).lower() == "na":
        if bathrooms is not None:
            if 1 <= bathrooms <= 3:
                specs["balconies"] = 1
            elif bathrooms >= 4:
                specs["balconies"] = 2
            else:
                specs["balconies"] = "na"
        else:
            specs["balconies"] = "na"

    if not specs.get("parking") or str(specs.get("parking")).lower() == "na":
        specs["parking"] = "YES"
    if not specs.get("facing_direction") or str(specs.get("facing_direction")).lower() == "na":
        specs["facing_direction"] = "NORTH WEST"

    data["specifications"] = specs

    loc = data.get("location", {})
    sub_loc = str(loc.get("sub_locality", "")).strip()
    if sub_loc and sub_loc.lower() != "na":
        loc["locality"] = sub_loc
        loc["sub_locality"] = sub_loc

    amenities = data.get("amenities")
    if not amenities or len(amenities) == 0:
        data["amenities"] = DEFAULT_AMENITIES

    address_parts = []
    for key in ["sub_locality", "locality", "landmark", "city", "state", "pincode"]:
        val = str(loc.get(key, "")).strip()
        if val and val.lower() != "na" and val not in address_parts:
            address_parts.append(val)
    
    if address_parts:
        loc["full_address"] = ", ".join(address_parts)
    else:
        loc["full_address"] = "na"

    data["location"] = loc

    media = data.get("media", {})
    media["images"] = uploaded_urls
    data["media"] = media

    return data

def call_gemini_rest_api(pil_images, prompt):
    if not API_KEY:
        raise Exception("GEMINI_API_KEY environment variable set nahi hai!")

    client = genai.Client(api_key=API_KEY)
    contents = [prompt] + pil_images

    config = types.GenerateContentConfig(
        response_mime_type="application/json"
    )

    # Working active models list (Deprecated models removed)
    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash"]

    last_err = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            return response.text
        except Exception as e:
            last_err = str(e)
            time.sleep(1)

    raise Exception(f"Gemini API Error: {last_err}")

@app.route('/')
def home():
    return render_template(
        'index.html',
        db_name=DB_NAME,
        collection_name=COLLECTION_NAME
    )

@app.route('/api/upload-cloudinary', methods=['POST'])
def upload_cloudinary():
    uploaded_files = request.files.getlist('images')
    if not uploaded_files or len(uploaded_files) == 0:
        return Response(json.dumps({"success": False, "error": "No image files provided"}), status=400, mimetype='application/json')

    urls = []
    try:
        for file in uploaded_files:
            file_bytes = file.read()
            upload_result = cloudinary.uploader.upload(file_bytes, folder="processed_images")
            urls.append(upload_result['secure_url'])
        return Response(json.dumps({"success": True, "urls": urls}), status=200, mimetype='application/json')
    except Exception as e:
        return Response(json.dumps({"success": False, "error": f"Cloudinary Error: {str(e)}"}), status=500, mimetype='application/json')

@app.route('/api/extract-json', methods=['POST'])
def extract_json():
    data_files = request.files.getlist('data_images')
    urls_raw = request.form.get('cloudinary_urls', '[]')
    
    try:
        uploaded_urls = json.loads(urls_raw)
    except Exception:
        uploaded_urls = []

    if not data_files or len(data_files) == 0:
        return Response(json.dumps({"success": False, "error": "No raw detail images provided"}), status=400, mimetype='application/json')

    try:
        pil_images = []
        for file in data_files:
            img_bytes = file.read()
            pil_images.append(Image.open(io.BytesIO(img_bytes)))

        prompt = f"""
        You are an expert real estate data extractor. Extract property details combining ALL uploaded images.
        Fit the extracted details into this exact JSON structure:
        {json.dumps(get_default_structure())}

        STRICT RULES FOR EXTRACTION:
        1. TITLE: "title_and_description.title" MUST contain ONLY the main dark bold property name.
        2. DESCRIPTION: "title_and_description.description" MUST contain the entire header line text.
        3. LOCATION & SUB_LOCALITY:
           - Extract the specific sub-locality/area. Set "locality" and "sub_locality" to be identical.
           - LANDMARK & PINCODE: Use web search knowledge to find nearest prominent LANDMARK and correct PINCODE.
        4. CONSTRUCTION STATUS:
           - If image mentions "under construction", set "construction_status" to "UNDER_CONSTRUCTION".
           - Otherwise set it to "READY_TO_MOVE".
        5. AREA SPECIFICATIONS (SQFT): Extract numeric sqft value if visible.
        6. Return ONLY raw JSON string without markdown wrappers.
        """

        raw_json_resp = call_gemini_rest_api(pil_images, prompt)
        
        clean_json_str = raw_json_resp.strip()
        if clean_json_str.startswith("```json"):
            clean_json_str = clean_json_str[7:]
        if clean_json_str.startswith("```"):
            clean_json_str = clean_json_str[3:]
        if clean_json_str.endswith("```"):
            clean_json_str = clean_json_str[:-3]

        extracted_json = json.loads(clean_json_str.strip())
        final_data = apply_custom_logic(extracted_json, uploaded_urls)

        template = get_default_structure()
        ordered_output = {}
        for key in template.keys():
            if key in final_data:
                ordered_output[key] = final_data[key]
            else:
                ordered_output[key] = template[key]

        return Response(json.dumps({"success": True, "data": ordered_output}), status=200, mimetype='application/json')

    except Exception as e:
        return Response(json.dumps({"success": False, "error": f"Extraction Failed: {str(e)}"}), status=500, mimetype='application/json')

@app.route('/api/submit-to-db', methods=['POST'])
def submit_to_db():
    try:
        collection = get_mongo_collection()
        data = request.get_json()
        raw_json_str = data.get("json_data", "")

        if not raw_json_str:
            return jsonify({"success": False, "error": "JSON data field is empty!"}), 400

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
      
