from flask import jsonify, request
from functools import wraps
import jwt
from config import Config

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 403
            
        try:
            data = jwt.decode(token.split()[1], Config.SECRET_KEY, algorithms=["HS256"])
        except:
            return jsonify({'message': 'Token is invalid!'}), 403
            
        return f(*args, **kwargs)
    return decorated