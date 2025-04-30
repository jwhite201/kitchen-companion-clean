from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from openai import OpenAI
from dotenv import load_dotenv
import re

# Expanded affiliate links with keyword variants
expanded_affiliate_links = {
    "mixer": {
        "keywords": ["mixer", "stand mixer", "hand mixer", "electric mixer", "kitchen mixer"],
        "url": "https://amzn.to/44QqzQf"
    },
    "mixing bowl": {
        "keywords": ["mixing bowl", "bowl", "baking bowl", "prep bowl"],
        "url": "https://amzn.to/3SepGJI"
    },
    "measuring cup": {
        "keywords": ["measuring cup", "measuring cups", "measuring tools"],
        "url": "https://amzn.to/44h5HBt"
    },
    "spatula": {
        "keywords": ["spatula", "rubber spatula", "silicone spatula"],
        "url": "https://amzn.to/4iILIiP"
    },
    "scale": {
        "keywords": ["scale", "kitchen scale", "digital scale", "food scale"],
        "url": "https://amzn.to/4cUBs5t"
    },
    "rolling pin": {
        "keywords": ["rolling pin", "dough roller", "pastry roller"],
        "url": "https://amzn.to/3Gy1mQv"
    },
    "6 inch pan": {
        "keywords": ["6 inch pan", "six inch cake pan", "6\" cake pan"],
        "url": "https://amzn.to/4lRwo64"
    },
    "9 inch pan": {
        "keywords": ["9 inch pan", "nine inch cake pan", "9\" cake pan"],
        "url": "https://amzn.to/42xSUtc"
    },
    "cake decorating": {
        "keywords": ["cake decorating", "piping tips", "frosting tools", "decorating kit", "icing tools"],
        "url": "https://amzn.to/4lUd08m"
    }
}

# Function to inject conversational affiliate links based on keyword variants

def add_affiliate_links_with_variants(response_text, product_map):
    recommendations = []
    lower_text = response_text.lower()

    print("\n[DEBUG] GPT Response (lowercased):\n", lower_text)

    for product, data in product_map.items():
        for keyword in data["keywords"]:
            pattern = re.compile(rf'(?<!\w){re.escape(keyword.lower())}(s)?(?!\w)')
            print(f"[DEBUG] Checking for keyword: '{keyword}' with pattern: '{pattern.pattern}'")
            if pattern.search(lower_text):
                print(f"[MATCH] Found keyword: {keyword} for product: {product}")
                if product == "mixer":
                    recommendations.append(f"\ud83d\udc49 Thinking about getting a mixer? [This one]({data['url']}) is my go-to.")
                elif product == "spatula":
                    recommendations.append(f"\ud83d\udc49 I swear by [this spatula]({data['url']})\u2014super handy in the kitchen.")
                elif product == "scale":
                    recommendations.append(f"\ud83d\udc49 For accuracy, [this kitchen scale]({data['url']}) does the trick.")
                elif product == "cake decorating":
                    recommendations.append(f"\ud83d\udc49 Want to level up your cake game? [This decorating kit]({data['url']}) is a must.")
                else:
                    recommendations.append(f"\ud83d\udc49 Check out [this {product}]({data['url']}) I recommend.")
                break

    if recommendations:
        print(f"[DEBUG] Appending {len(recommendations)} affiliate link(s).")
        response_text += "\n\n" + "\n".join(recommendations)
    else:
        print("[DEBUG] No affiliate keywords matched.")

    return response_text

# Load environment variables from .env
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Load API keys
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

@app.route('/')
def home():
    return "Kitchen Companion is live!"

# GPT Assistant endpoint
@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    user_input = data.get('message')

    if not user_input:
        return jsonify({"error": "No message provided"}), 400

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are The Kitchen Companion, a smart and helpful AI chef assistant. Always suggest healthy, realistic, and inspiring ideas. When suggesting tools or equipment, use specific names like 'mixer', 'scale', or 'cake pan' where appropriate."},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content

        # Inject affiliate links with better keyword matching
        reply_with_links = add_affiliate_links_with_variants(reply, expanded_affiliate_links)

        return jsonify({"reply": reply_with_links})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Recipe Search endpoint
@app.route('/search_recipes', methods=['GET'])
def search_recipes():
    query = request.args.get('query')
    diet = request.args.get('diet')
    max_ready_time = request.args.get('maxReadyTime')
    number = request.args.get('number', default=5)

    if not query:
        return jsonify({'error': 'Missing query parameter'}), 400

    url = 'https://api.spoonacular.com/recipes/complexSearch'
    params = {
        'query': query,
        'number': number,
        'apiKey': SPOONACULAR_API_KEY
    }

    if diet:
        params['diet'] = diet
    if max_ready_time:
        params['maxReadyTime'] = max_ready_time

    response = requests.get(url, params=params)

    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({'error': 'API call failed', 'details': response.text}), response.status_code

# Recipe Details endpoint
@app.route('/get_recipe_details', methods=['GET'])
def get_recipe_details():
    recipe_id = request.args.get('id')

    if not recipe_id:
        return jsonify({'error': 'Missing id parameter'}), 400

    url = f'https://api.spoonacular.com/recipes/{recipe_id}/information'
    params = {'apiKey': SPOONACULAR_API_KEY}

    response = requests.get(url, params=params)

    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({'error': 'API call failed', 'details': response.text}), response.status_code

# Run the Flask app on Render
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
