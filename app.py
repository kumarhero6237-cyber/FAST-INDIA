#  UNCOMMON CORE ON TOP BABY !!!
#  INDIA ONLY INFO API - MODIFIED VERSION
#  RETURNS ONLY INDIA REGION PLAYER INFO IN JSON
#  JOIN @uncommoncore FOR MORE LEAKS

import asyncio
import time
import httpx
import json
import random
import threading
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from typing import Tuple
from proto import FreeFire_pb2, main_pb2, AccountPersonalShow_pb2
from google.protobuf import json_format, message
from google.protobuf.message import Message
from Crypto.Cipher import AES
import base64

# ---------- Config ----------

MAIN_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
MAIN_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
RELEASEVERSION = "OB54"
USERAGENT = "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)"

# ONLY INDIA REGION
SUPPORTED_REGIONS = ["IND"]

# ---------- API KEY SYSTEM ----------

API_KEY = "RAM-SAGAR"

# ---------- App Setup ----------

app = Flask(__name__)
CORS(app)
cached_tokens = {}

# ---------- API KEY DECORATOR ----------

def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = request.args.get("key") or request.headers.get("x-api-key")
        if key != API_KEY:
            return jsonify({"error": "Invalid or missing API key"}), 403
        return fn(*args, **kwargs)
    return wrapper

# ----------- Helper Functions ------------

def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(pad(plaintext))

def decode_protobuf(encoded_data: bytes, message_type: message.Message) -> message.Message:
    instance = message_type()
    instance.ParseFromString(encoded_data)
    return instance

async def json_to_proto(json_data: str, proto_message: Message) -> bytes:
    json_format.ParseDict(json.loads(json_data), proto_message)
    return proto_message.SerializeToString()

# -------------- INDIA Guest Account --------------

def get_india_account() -> str:
    return "uid=4732484418&password=BP_E7AKQ4YVHCB"

# -------------- Token Generation --------------

async def get_access_token(account: str):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = account + "&response_type=token&client_type=2&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3&client_id=100067"
    headers = {
        'User-Agent': USERAGENT,
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Content-Type': "application/x-www-form-urlencoded"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=payload, headers=headers)
        data = resp.json()
        return data.get("access_token", "0"), data.get("open_id", "0")


async def create_jwt():
    account = get_india_account()
    token_val, open_id = await get_access_token(account)

    body = json.dumps({
        "open_id": open_id,
        "open_id_type": "4",
        "login_token": token_val,
        "orign_platform_type": "4"
    })

    proto_bytes = await json_to_proto(body, FreeFire_pb2.LoginReq())
    payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)

    url = "https://loginbp.ggpolarbear.com/MajorLogin"
    headers = {
        'User-Agent': USERAGENT,
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Content-Type': "application/octet-stream",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': RELEASEVERSION
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, data=payload, headers=headers)

        if resp.status_code != 200 or resp.headers.get("content-type") != "application/octet-stream":
            print(f"❌ TOKEN FAIL [IND]: Status={resp.status_code}, Content={resp.content}")
            return False

        try:
            decoded = decode_protobuf(resp.content, FreeFire_pb2.LoginRes)
            msg = json.loads(json_format.MessageToJson(decoded))
        except Exception as e:
            print(f"❌ PROTO FAIL [IND]:", e)
            return False

        cached_tokens['IND'] = {
            'token': f"Bearer {msg.get('token','0')}",
            'region': msg.get('lockRegion','0'),
            'server_url': msg.get('serverUrl','0'),
            'expires_at': time.time() + 25200
        }

        print(f"✅ TOKEN OK [IND] -> Server: {msg.get('serverUrl','0')}")
        return True


async def initialize_tokens():
    await create_jwt()

async def refresh_tokens_periodically():
    while True:
        await asyncio.sleep(25200)
        await initialize_tokens()

async def get_token_info() -> Tuple[str, str, str]:
    info = cached_tokens.get('IND')

    if info and time.time() < info['expires_at']:
        return info['token'], info['region'], info['server_url']

    success = await create_jwt()
    if not success:
        raise Exception("Failed to generate token for IND region")

    info = cached_tokens['IND']
    return info['token'], info['region'], info['server_url']

async def GetAccountInformation(uid, unk):
    payload = await json_to_proto(
        json.dumps({'a': uid, 'b': unk}),
        main_pb2.GetPlayerPersonalShow()
    )

    data_enc = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, payload)
    token, lock, server = await get_token_info()

    headers = {
        'User-Agent': USERAGENT,
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Content-Type': "application/octet-stream",
        'Expect': "100-continue",
        'Authorization': token,
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': RELEASEVERSION
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(server + "/GetPlayerPersonalShow", data=data_enc, headers=headers)

        if resp.status_code != 200:
            raise Exception(f"Server returned status {resp.status_code}")

        if resp.headers.get("content-type") != "application/octet-stream":
            raise Exception(f"Unexpected content type: {resp.headers.get('content-type')}")

        decoded = decode_protobuf(resp.content, AccountPersonalShow_pb2.AccountPersonalShowInfo)
        return json.loads(json_format.MessageToJson(decoded))

# -------------- Routes Endpoints --------------

@app.route('/uc-info')
@require_api_key
def get_account_info():
    uid = request.args.get('uid')

    if not uid:
        return jsonify({"error": "Please provide UID. Example: /uc-info?uid=123456789&key=RAM-SAGAR"}), 400

    # Validate UID is numeric
    if not uid.isdigit():
        return jsonify({"error": "UID must be a valid number"}), 400

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        data = loop.run_until_complete(GetAccountInformation(uid, "7"))

        # Return clean JSON response
        return json.dumps(data, indent=2), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        error_msg = str(e)
        print(f"❌ ERROR fetching UID {uid}: {error_msg}")
        return jsonify({"error": "Failed to fetch player info", "details": error_msg}), 500


@app.route('/ref-token', methods=['GET', 'POST'])
@require_api_key
def refresh_tokens_endpoint():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(create_jwt())

        if success:
            return jsonify({'message': 'India token refreshed successfully'}), 200
        else:
            return jsonify({'error': 'Token refresh failed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/')
def home():
    return jsonify({
        "api": "UC India Only Free Fire Info API",
        "version": RELEASEVERSION,
        "region": "IND ONLY",
        "endpoints": {
            "/uc-info?uid=<UID>&key=RAM-SAGAR": "Get India player info",
            "/ref-token?key=RAM-SAGAR": "Refresh auth token",
            "/": "This info"
        }
    })


# -------------- async Startup --------------

started = False

def start_background_loop():
    global started
    if started:
        return
    started = True

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(initialize_tokens())
    loop.create_task(refresh_tokens_periodically())
    loop.run_forever()

threading.Thread(target=start_background_loop, daemon=True).start()
