import json
import os

# Read the original credentials
with open('firebase-credentials.json', 'r') as f:
    creds = json.load(f)

# Format the private key properly
if 'private_key' in creds:
    # Ensure proper PEM format
    private_key = creds['private_key']
    if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
        private_key = '-----BEGIN PRIVATE KEY-----\n' + private_key
    if not private_key.endswith('-----END PRIVATE KEY-----'):
        private_key = private_key + '\n-----END PRIVATE KEY-----'
    creds['private_key'] = private_key

# Convert to JSON string with proper escaping
creds_str = json.dumps(creds)

# Print the formatted credentials
print("FIREBASE_SERVICE_ACCOUNT=" + creds_str)

# Save to a file
with open('firebase_creds_formatted.txt', 'w') as f:
    f.write("FIREBASE_SERVICE_ACCOUNT=" + creds_str) 