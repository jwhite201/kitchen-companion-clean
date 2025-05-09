from flask import Flask, request, jsonify, session
from flask_cors import CORS
import requests
import os
from openai import OpenAI
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import re
import logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
import jsonschema
from jsonschema import validate
from passlib.hash import pbkdf2_sha256
import jwt
from datetime import datetime, timedelta
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email_validator import validate_email, EmailNotValidError
import secrets
from flask_session import Session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Validate required environment variables
required_env_vars = [
    "OPENAI_API_KEY", 
    "SPOONACULAR_API_KEY", 
    "JWT_SECRET_KEY",
    "SMTP_SERVER",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "APP_URL"
]
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Initialize Firebase
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate("firebase-service-account.json")
        firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {str(e)}")
    raise

app = Flask(__name__)

# Configure session
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
Session(app)

# Configure rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Configure CORS with specific origins
CORS(app, resources={r"/*": {"origins": os.getenv("ALLOWED_ORIGINS", "*").split(",")}})

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

# Email Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
APP_URL = os.getenv("APP_URL")

# JSON Schemas for request validation
recipe_schema = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "recipe": {
            "type": "object",
            "required": ["title", "ingredients", "instructions"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "ingredients": {"type": "array", "items": {"type": "string"}},
                "instructions": {"type": "string", "minLength": 1}
            }
        }
    },
    "required": ["user_id", "recipe"]
}

pantry_schema = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "pantry": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["user_id", "pantry"]
}

grocery_list_schema = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "grocery_list": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["user_id", "grocery_list"]
}

gpt_request_schema = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["user", "assistant", "system"]},
                    "content": {"type": "string", "minLength": 1}
                },
                "required": ["role", "content"]
            }
        }
    },
    "required": ["messages"]
}

# Authentication schemas
auth_schema = {
    "type": "object",
    "properties": {
        "username": {"type": "string", "minLength": 3, "maxLength": 50},
        "password": {"type": "string", "minLength": 8},
        "email": {"type": "string", "format": "email"}
    },
    "required": ["username", "password", "email"]
}

profile_schema = {
    "type": "object",
    "properties": {
        "display_name": {"type": "string", "maxLength": 100},
        "bio": {"type": "string", "maxLength": 500},
        "preferences": {
            "type": "object",
            "properties": {
                "dietary_restrictions": {"type": "array", "items": {"type": "string"}},
                "cooking_skill_level": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
                "favorite_cuisines": {"type": "array", "items": {"type": "string"}}
            }
        }
    }
}

def send_email(to_email, subject, body):
    """Send email using configured SMTP server"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

def generate_token(user_id, token_type='access'):
    """Generate JWT token for user"""
    expires = JWT_ACCESS_TOKEN_EXPIRES if token_type == 'access' else JWT_REFRESH_TOKEN_EXPIRES
    payload = {
        'user_id': user_id,
        'type': token_type,
        'exp': datetime.utcnow() + expires
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')

def verify_token(token):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        return payload['user_id'], payload['type']
    except jwt.ExpiredSignatureError:
        return None, None
    except jwt.InvalidTokenError:
        return None, None

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        if token.startswith('Bearer '):
            token = token[7:]
        
        user_id, token_type = verify_token(token)
        if not user_id or token_type != 'access':
            return jsonify({'error': 'Invalid or expired token'}), 401
            
        return f(user_id, *args, **kwargs)
    return decorated

def validate_json(schema):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400
            try:
                validate(instance=request.get_json(), schema=schema)
            except jsonschema.exceptions.ValidationError as e:
                return jsonify({"error": f"Invalid request data: {str(e)}"}), 400
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def sanitize_input(text):
    """Basic input sanitization"""
    if not isinstance(text, str):
        return ""
    # Remove any HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove any script tags
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)
    # Remove any potentially dangerous characters
    text = re.sub(r'[<>{}[\]\\]', '', text)
    return text.strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

affiliate_links = {
    "mixer": "https://amzn.to/44QqzQf", "mixing bowl": "https://amzn.to/3SepGJI",
    "measuring cup": "https://amzn.to/44h5HBt", "spatula": "https://amzn.to/4iILIiP",
    "scale": "https://amzn.to/4cUBs5t", "rolling pin": "https://amzn.to/3Gy1mQv",
    "6 inch pan": "https://amzn.to/4lRwo64", "9 inch pan": "https://amzn.to/42xSUtc",
    "cake decorating": "https://amzn.to/4lUd08m", "whisk": "https://amzn.to/3GwiBlk",
    "bench scraper": "https://amzn.to/3GzcuN2", "loaf pan": "https://amzn.to/42XzcpD",
    "almond flour": "https://amzn.to/4iCs3kx", "no sugar added chocolate chips": "https://amzn.to/3SfqlKU",
    "monk fruit sweetener": "https://amzn.to/4cSRP2u", "coconut sugar": "https://amzn.to/42TZN6S",
    "whole wheat flour": "https://amzn.to/4jAbpmQ", "cake flour": "https://amzn.to/3YmwUz1",
    "silicone baking mat": "https://amzn.to/4jJcRmI", "avocado oil": "https://amzn.to/3EwlK43",
    "digital thermometer": "https://amzn.to/42SIDXr", "food storage containers": "https://amzn.to/4k1U7ip",
    "baking sheet": "https://amzn.to/44ijPdO", "hand mixer": "https://amzn.to/437UVwi",
    "wire racks": "https://amzn.to/42Rghg3", "cookie scoop": "https://amzn.to/3EH8Yjd",
    "food processor": "https://amzn.to/4iLcbvY", "matcha": "https://amzn.to/4d0bGwL",
    "cocoa powder": "https://amzn.to/42WB3Lp"
}

def add_affiliate_links(text):
    added = 0
    for keyword, url in affiliate_links.items():
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) and added < 4:
            text = re.sub(rf"\b({re.escape(keyword)})\b", f"[\\1]({url})", text, count=1, flags=re.IGNORECASE)
            added += 1
    return text

def extract_ingredients(text):
    lines = text.split('\n')
    ingredients = []
    for line in lines:
        match = re.match(r'- (.+)', line)
        if match:
            ingredient = re.sub(r'\d+([\/\.]?\d+)?\s?(cups?|cup|tbsp|tsp|oz|g|ml)?\s?', '', match.group(1), flags=re.IGNORECASE)
            ingredients.append(ingredient.strip())
    return list(set(ingredients))

@app.route('/')
def home():
    return jsonify({"message": "Kitchen Companion backend is live!"})

@app.route('/ask_gpt', methods=['POST'])
@limiter.limit("10 per minute")
@validate_json(gpt_request_schema)
def ask_gpt():
    try:
        data = request.get_json()
        messages = data.get('messages')
        
        # Sanitize user messages
        for message in messages:
            if message.get('role') == 'user':
                message['content'] = sanitize_input(message['content'])

        user_message = [m['content'] for m in messages if m['role'] == 'user']
        if not user_message:
            return jsonify({"error": "No user message found"}), 400
        user_message = user_message[-1]

        system_prompt = {
            "role": "system",
            "content": (
                "You are Jake's Kitchen Companion, a sharp, witty, and sometimes cheeky culinary assistant. You serve up expert-level cooking advice with a splash of humor and a dash of sass. Channel a mix of Martha Stewart's polish, Gordon Ramsay's directness (without the swearing), and a best friend's playful sarcasm. Keep recipes precise and helpful, but don't be afraid to toss in a clever joke or playful banter. Stay charming, confident, and fun — but never mean or offensive. Help users cook amazing meals, suggest creative swaps, and make the kitchen feel like the coolest place in the house."
                "who channels the refinement of Martha Stewart and the fearless creativity of Julia Child. "
                "You help users cook confidently with high-quality recipe suggestions, smart ingredient swaps, "
                "kitchen hacks, prep tips, and clear instructions. Always prioritize accuracy, clarity, and "
                "trusted sources (like USDA, Mayo Clinic). Default to giving full, detailed recipes when a dish is requested. "
                "Offer helpful context or background only if the user asks. You handle dietary needs (vegan, gluten-free, "
                "dairy-free, sugar-free) and scale recipes with precise unit conversions. Your tone is clear, direct, and no-nonsense—"
                "cut the fluff—but still thoughtful and charming. You've got a chill, sharp, bro-like vibe: work hard, vibe harder. "
                "Efficient but never stiff. Cool but never careless. You never invent health claims and you always ask clarifying questions "
                "if the user's request is vague. You also help with meal planning, grocery lists, pantry use, and creative leftovers."
            )
        }
        messages.insert(0, system_prompt)

        try:
            gpt_response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                max_tokens=700,
                temperature=0.7
            )
            reply = gpt_response.choices[0].message.content
            reply = add_affiliate_links(reply)
            title_line = f"🍽️ Recipe: {user_message.title()}\n\n"
            reply = title_line + reply
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            return jsonify({"error": "Failed to generate recipe response"}), 500

        try:
            spoonacular_resp = requests.get(
                "https://api.spoonacular.com/recipes/complexSearch",
                params={'query': user_message, 'number': 1, 'addRecipeNutrition': True, 'apiKey': SPOONACULAR_API_KEY},
                timeout=10  # Add timeout
            )
            spoonacular_resp.raise_for_status()  # Raise exception for bad status codes

            image_url, nutrition, servings, time = None, None, None, None
            if spoonacular_resp.status_code == 200:
                res = spoonacular_resp.json()
                if res.get('results'):
                    item = res['results'][0]
                    image_url = item.get('image')
                    nutrition = item.get('nutrition', {}).get('nutrients')
                    servings = item.get('servings')
                    time = item.get('readyInMinutes')
        except requests.exceptions.RequestException as e:
            logger.error(f"Spoonacular API error: {str(e)}")
            # Continue without Spoonacular data rather than failing completely
            image_url, nutrition, servings, time = None, None, None, None

        try:
            ingredients = extract_ingredients(reply)
        except Exception as e:
            logger.error(f"Error extracting ingredients: {str(e)}")
            ingredients = []

        return jsonify({
            "reply": reply,
            "image_url": image_url,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "ingredients": ingredients
        })
    except Exception as e:
        logger.error(f"Unexpected error in ask_gpt: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/register', methods=['POST'])
@limiter.limit("5 per minute")
@validate_json(auth_schema)
def register():
    try:
        data = request.get_json()
        username = sanitize_input(data.get('username'))
        password = data.get('password')
        email = data.get('email')

        # Validate email
        try:
            validate_email(email)
        except EmailNotValidError:
            return jsonify({'error': 'Invalid email address'}), 400

        # Check if username or email already exists
        users_ref = db.collection('users')
        username_query = users_ref.where('username', '==', username).limit(1).get()
        email_query = users_ref.where('email', '==', email).limit(1).get()
        
        if len(username_query) > 0:
            return jsonify({'error': 'Username already exists'}), 400
        if len(email_query) > 0:
            return jsonify({'error': 'Email already exists'}), 400

        # Hash password
        hashed_password = pbkdf2_sha256.hash(password)
        
        # Generate verification token
        verification_token = secrets.token_urlsafe(32)
        
        # Create user document
        user_id = str(uuid.uuid4())
        user_data = {
            'username': username,
            'email': email,
            'password': hashed_password,
            'created_at': datetime.utcnow().isoformat(),
            'auth_provider': 'local',
            'is_verified': False,
            'verification_token': verification_token,
            'verification_token_expires': (datetime.utcnow() + timedelta(hours=24)).isoformat()
        }
        
        users_ref.document(user_id).set(user_data)
        
        # Send verification email
        verification_url = f"{APP_URL}/verify-email?token={verification_token}"
        email_body = f"""
        <h1>Welcome to Kitchen Companion!</h1>
        <p>Please click the link below to verify your email address:</p>
        <p><a href="{verification_url}">Verify Email</a></p>
        """
        send_email(email, "Verify your email address", email_body)
        
        # Generate tokens
        access_token = generate_token(user_id, 'access')
        refresh_token = generate_token(user_id, 'refresh')
        
        return jsonify({
            'message': 'User registered successfully. Please check your email to verify your account.',
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user_id': user_id
        }), 201
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({'error': 'Failed to register user'}), 500

@app.route('/verify-email', methods=['GET'])
def verify_email():
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'error': 'Verification token is missing'}), 400

        # Find user with this verification token
        users_ref = db.collection('users')
        query = users_ref.where('verification_token', '==', token).limit(1).get()
        
        if len(query) == 0:
            return jsonify({'error': 'Invalid verification token'}), 400
            
        user_doc = query[0]
        user_data = user_doc.to_dict()
        
        # Check if token is expired
        token_expires = datetime.fromisoformat(user_data['verification_token_expires'])
        if datetime.utcnow() > token_expires:
            return jsonify({'error': 'Verification token has expired'}), 400
            
        # Update user as verified
        user_doc.reference.update({
            'is_verified': True,
            'verification_token': None,
            'verification_token_expires': None
        })
        
        return jsonify({'message': 'Email verified successfully'})
        
    except Exception as e:
        logger.error(f"Email verification error: {str(e)}")
        return jsonify({'error': 'Failed to verify email'}), 500

@app.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
@validate_json(auth_schema)
def login():
    try:
        data = request.get_json()
        username = sanitize_input(data.get('username'))
        password = data.get('password')

        # Find user by username
        users_ref = db.collection('users')
        query = users_ref.where('username', '==', username).limit(1).get()
        
        if len(query) == 0:
            return jsonify({'error': 'Invalid username or password'}), 401
            
        user_doc = query[0]
        user_data = user_doc.to_dict()
        
        # Verify password
        if not pbkdf2_sha256.verify(password, user_data['password']):
            return jsonify({'error': 'Invalid username or password'}), 401
            
        # Check if email is verified
        if not user_data.get('is_verified', False):
            return jsonify({'error': 'Please verify your email before logging in'}), 401
            
        # Generate tokens
        access_token = generate_token(user_doc.id, 'access')
        refresh_token = generate_token(user_doc.id, 'refresh')
        
        # Store session data
        session['user_id'] = user_doc.id
        session['last_activity'] = datetime.utcnow().isoformat()
        
        return jsonify({
            'message': 'Login successful',
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user_id': user_doc.id
        })
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Failed to login'}), 500

@app.route('/refresh-token', methods=['POST'])
def refresh_token():
    try:
        refresh_token = request.json.get('refresh_token')
        if not refresh_token:
            return jsonify({'error': 'Refresh token is missing'}), 400
            
        user_id, token_type = verify_token(refresh_token)
        if not user_id or token_type != 'refresh':
            return jsonify({'error': 'Invalid or expired refresh token'}), 401
            
        # Generate new access token
        access_token = generate_token(user_id, 'access')
        
        return jsonify({
            'access_token': access_token
        })
        
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        return jsonify({'error': 'Failed to refresh token'}), 500

@app.route('/forgot-password', methods=['POST'])
@limiter.limit("3 per hour")
def forgot_password():
    try:
        email = request.json.get('email')
        if not email:
            return jsonify({'error': 'Email is required'}), 400
            
        # Find user by email
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1).get()
        
        if len(query) == 0:
            return jsonify({'error': 'No account found with this email'}), 404
            
        user_doc = query[0]
        
        # Generate password reset token
        reset_token = secrets.token_urlsafe(32)
        reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        
        # Update user document
        user_doc.reference.update({
            'reset_token': reset_token,
            'reset_token_expires': reset_token_expires.isoformat()
        })
        
        # Send password reset email
        reset_url = f"{APP_URL}/reset-password?token={reset_token}"
        email_body = f"""
        <h1>Password Reset Request</h1>
        <p>Click the link below to reset your password:</p>
        <p><a href="{reset_url}">Reset Password</a></p>
        <p>This link will expire in 1 hour.</p>
        """
        send_email(email, "Reset your password", email_body)
        
        return jsonify({'message': 'Password reset instructions sent to your email'})
        
    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        return jsonify({'error': 'Failed to process password reset request'}), 500

@app.route('/reset-password', methods=['POST'])
@limiter.limit("3 per hour")
def reset_password():
    try:
        token = request.json.get('token')
        new_password = request.json.get('new_password')
        
        if not token or not new_password:
            return jsonify({'error': 'Token and new password are required'}), 400
            
        # Find user with this reset token
        users_ref = db.collection('users')
        query = users_ref.where('reset_token', '==', token).limit(1).get()
        
        if len(query) == 0:
            return jsonify({'error': 'Invalid reset token'}), 400
            
        user_doc = query[0]
        user_data = user_doc.to_dict()
        
        # Check if token is expired
        token_expires = datetime.fromisoformat(user_data['reset_token_expires'])
        if datetime.utcnow() > token_expires:
            return jsonify({'error': 'Reset token has expired'}), 400
            
        # Hash new password
        hashed_password = pbkdf2_sha256.hash(new_password)
        
        # Update user document
        user_doc.reference.update({
            'password': hashed_password,
            'reset_token': None,
            'reset_token_expires': None
        })
        
        return jsonify({'message': 'Password reset successful'})
        
    except Exception as e:
        logger.error(f"Password reset error: {str(e)}")
        return jsonify({'error': 'Failed to reset password'}), 500

@app.route('/profile', methods=['GET'])
@token_required
def get_profile(user_id):
    try:
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
            
        user_data = user_doc.to_dict()
        # Remove sensitive data
        user_data.pop('password', None)
        user_data.pop('reset_token', None)
        user_data.pop('reset_token_expires', None)
        user_data.pop('verification_token', None)
        user_data.pop('verification_token_expires', None)
        
        return jsonify(user_data)
        
    except Exception as e:
        logger.error(f"Get profile error: {str(e)}")
        return jsonify({'error': 'Failed to get profile'}), 500

@app.route('/profile', methods=['PUT'])
@token_required
@validate_json(profile_schema)
def update_profile(user_id):
    try:
        data = request.get_json()
        
        # Update user document
        db.collection('users').document(user_id).update({
            'display_name': sanitize_input(data.get('display_name')),
            'bio': sanitize_input(data.get('bio')),
            'preferences': data.get('preferences', {})
        })
        
        return jsonify({'message': 'Profile updated successfully'})
        
    except Exception as e:
        logger.error(f"Update profile error: {str(e)}")
        return jsonify({'error': 'Failed to update profile'}), 500

@app.route('/change-password', methods=['POST'])
@token_required
def change_password(user_id):
    try:
        data = request.get_json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return jsonify({'error': 'Current password and new password are required'}), 400
            
        # Get user document
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
            
        user_data = user_doc.to_dict()
        
        # Verify current password
        if not pbkdf2_sha256.verify(current_password, user_data['password']):
            return jsonify({'error': 'Current password is incorrect'}), 401
            
        # Hash new password
        hashed_password = pbkdf2_sha256.hash(new_password)
        
        # Update password
        user_doc.reference.update({
            'password': hashed_password
        })
        
        return jsonify({'message': 'Password changed successfully'})
        
    except Exception as e:
        logger.error(f"Change password error: {str(e)}")
        return jsonify({'error': 'Failed to change password'}), 500

@app.route('/logout', methods=['POST'])
@token_required
def logout(user_id):
    try:
        # Clear session data
        session.clear()
        return jsonify({'message': 'Logged out successfully'})
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return jsonify({'error': 'Failed to logout'}), 500

@app.route('/save_recipe', methods=['POST'])
@limiter.limit("20 per minute")
@token_required
@validate_json(recipe_schema)
def save_recipe(user_id):
    try:
        data = request.get_json()
        recipe = data.get('recipe')
        
        # Sanitize recipe data
        recipe['title'] = sanitize_input(recipe['title'])
        recipe['ingredients'] = [sanitize_input(ing) for ing in recipe['ingredients']]
        recipe['instructions'] = sanitize_input(recipe['instructions'])

        try:
            db.collection('users').document(user_id).collection('recipes').add(recipe)
            return jsonify({"status": "Recipe saved"})
        except Exception as e:
            logger.error(f"Firebase error saving recipe: {str(e)}")
            return jsonify({"error": "Failed to save recipe"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in save_recipe: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/get_recipes', methods=['GET'])
@token_required
def get_recipes(user_id):
    try:
        try:
            recipes = []
            docs = db.collection('users').document(user_id).collection('recipes').stream()
            for doc in docs:
                r = doc.to_dict()
                r['id'] = doc.id
                recipes.append(r)
            return jsonify(recipes)
        except Exception as e:
            logger.error(f"Firebase error getting recipes: {str(e)}")
            return jsonify({"error": "Failed to retrieve recipes"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in get_recipes: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/delete_recipe', methods=['DELETE'])
@token_required
def delete_recipe(user_id):
    try:
        recipe_id = request.args.get('recipe_id')
        if not recipe_id:
            return jsonify({'error': 'Missing recipe_id'}), 400

        try:
            recipe_ref = db.collection('users').document(user_id).collection('recipes').document(recipe_id)
            if not recipe_ref.get().exists:
                return jsonify({'error': 'Recipe not found'}), 404

            recipe_ref.delete()
            return jsonify({'message': 'Recipe deleted successfully'}), 200
        except Exception as e:
            logger.error(f"Firebase error deleting recipe: {str(e)}")
            return jsonify({"error": "Failed to delete recipe"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in delete_recipe: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/update_pantry', methods=['POST'])
@limiter.limit("20 per minute")
@token_required
@validate_json(pantry_schema)
def update_pantry(user_id):
    try:
        data = request.get_json()
        pantry_items = [sanitize_input(item) for item in data.get('pantry')]

        try:
            db.collection('users').document(user_id).update({'pantry': pantry_items})
            return jsonify({"status": "Pantry updated"})
        except Exception as e:
            logger.error(f"Firebase error updating pantry: {str(e)}")
            return jsonify({"error": "Failed to update pantry"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in update_pantry: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/update_grocery_list', methods=['POST'])
@limiter.limit("20 per minute")
@token_required
@validate_json(grocery_list_schema)
def update_grocery_list(user_id):
    try:
        data = request.get_json()
        grocery_items = [sanitize_input(item) for item in data.get('grocery_list')]

        try:
            db.collection('users').document(user_id).update({'grocery_list': grocery_items})
            return jsonify({"status": "Grocery list updated"})
        except Exception as e:
            logger.error(f"Firebase error updating grocery list: {str(e)}")
            return jsonify({"error": "Failed to update grocery list"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in update_grocery_list: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/save_pantry', methods=['POST'])
@token_required
def save_pantry(user_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        pantry = data.get('pantry')
        if pantry is None:
            return jsonify({"error": "Missing pantry"}), 400
            
        try:
            db.collection('users').document(user_id).set({'pantry': pantry}, merge=True)
            return jsonify({"status": "Pantry saved"})
        except Exception as e:
            logger.error(f"Firebase error saving pantry: {str(e)}")
            return jsonify({"error": "Failed to save pantry"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in save_pantry: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/get_pantry', methods=['GET'])
@token_required
def get_pantry(user_id):
    try:
        try:
            doc = db.collection('users').document(user_id).get()
            pantry = doc.to_dict().get('pantry', []) if doc.exists else []
            return jsonify({"pantry": pantry})
        except Exception as e:
            logger.error(f"Firebase error getting pantry: {str(e)}")
            return jsonify({"error": "Failed to retrieve pantry"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in get_pantry: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/get_recipe_detail', methods=['GET'])
@token_required
def get_recipe_detail(user_id):
    try:
        recipe_id = request.args.get('recipe_id')
        if not recipe_id:
            return jsonify({"error": "Missing recipe_id"}), 400
            
        try:
            doc = db.collection('users').document(user_id).collection('recipes').document(recipe_id).get()
            if not doc.exists:
                return jsonify({"error": "Recipe not found"}), 404
            return jsonify(doc.to_dict())
        except Exception as e:
            logger.error(f"Firebase error getting recipe detail: {str(e)}")
            return jsonify({"error": "Failed to retrieve recipe details"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in get_recipe_detail: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)