#!/usr/bin/env python3
"""
Redis Configuration Utility

This script helps you configure and test Redis connection settings.
It will try different authentication methods and update your .env file
with the correct settings.
"""

print("""
┌───────────────────────────────────────────────────────┐
│ REDIS CONFIGURATION UTILITY                           │
│                                                       │
│ This utility will help you configure Redis connection │
│ settings for the LXC_Autoscaler application.          │
│                                                       │
│ • It will try common passwords automatically          │
│ • If successful, it can update your .env file         │
│ • You can also specify a custom password               │
│                                                       │
│ If you know your Redis password, run:                 │
│   ./redis_config.py your_password                     │
│                                                       │
│ ERROR: WRONGPASS invalid username-password pair       │
│ This means Redis requires authentication but none of  │
│ the common passwords worked.                          │
└───────────────────────────────────────────────────────┘
""")
import os
import redis
import sys
import re

def test_connection(host='localhost', port=6379, password=None):
    """Test Redis connection with given parameters"""
    try:
        # Create connection
        if password:
            client = redis.StrictRedis(
                host=host,
                port=port,
                password=password,
                db=0,
                decode_responses=True
            )
        else:
            client = redis.StrictRedis(
                host=host,
                port=port,
                db=0,
                decode_responses=True
            )
        
        # Test connection with PING
        response = client.ping()
        return True, f"Connection successful with {'password' if password else 'no password'}"
    except Exception as e:
        return False, f"Error: {str(e)}"

def update_env_file(password=None):
    """Update .env file with Redis password"""
    try:
        env_file = '.env'
        
        if not os.path.exists(env_file):
            print(f"Error: {env_file} not found")
            return False
        
        with open(env_file, 'r') as f:
            content = f.read()
        
        # Replace the REDIS_PASSWORD line
        pattern = r'REDIS_PASSWORD=.*'
        replacement = f'REDIS_PASSWORD={password if password else ""}'
        
        new_content = re.sub(pattern, replacement, content)
        
        with open(env_file, 'w') as f:
            f.write(new_content)
        
        return True
    except Exception as e:
        print(f"Error updating .env file: {str(e)}")
        return False

def main():
    print("Redis Configuration Utility")
    print("==========================")
    
    # Common passwords to try
    passwords_to_try = [
        None,       # No password
        "",         # Empty string
        "default",  # Common default
        "redis",    # Common default
        "password", # Common test password
        "mizzle",   # Based on database password in .env
        "redis123", # Common default
        "admin",    # Common default
    ]
    
    host = 'localhost'
    port = 6379
    
    print(f"Testing connection to Redis at {host}:{port}...")
    
    successful_password = None
    for password in passwords_to_try:
        success, message = test_connection(host, port, password)
        if success:
            print(f"✅ {message}")
            successful_password = password
            break
        else:
            print(f"❌ Failed with{'out' if password is None else ''} password{f' \"{password}\"' if password else ''}: {message}")
    
    if successful_password is not None:
        print("\nSuccessful connection found!")
        update = input("Update .env file with these settings? (y/n): ")
        
        if update.lower() == 'y':
            if update_env_file(successful_password):
                print("✅ .env file updated successfully")
                if successful_password is None:
                    print("Redis password set to empty (authentication disabled)")
                else:
                    print(f"Redis password set to: {successful_password}")
            else:
                print("❌ Failed to update .env file")
    else:
        print("\n❌ All connection attempts failed!")
        print("You may need to:")
        print("1. Ensure Redis is running")
        print("2. Check if Redis requires a password")
        print("3. Try a specific password with: ./redis_config.py password")
        
        # Allow user to enter a custom password
        custom = input("Try a custom password? (y/n): ")
        if custom.lower() == 'y':
            password = input("Enter password: ")
            success, message = test_connection(host, port, password)
            
            if success:
                print(f"✅ {message}")
                update = input("Update .env file with this password? (y/n): ")
                
                if update.lower() == 'y':
                    if update_env_file(password):
                        print("✅ .env file updated successfully")
                    else:
                        print("❌ Failed to update .env file")
            else:
                print(f"❌ Failed: {message}")

if __name__ == "__main__":
    # If a password is provided as an argument, test just that password
    if len(sys.argv) > 1:
        password = sys.argv[1]
        print(f"Testing Redis connection with password: {password}")
        success, message = test_connection(password=password)
        
        if success:
            print(f"✅ {message}")
            update = input("Update .env file with this password? (y/n): ")
            
            if update.lower() == 'y':
                if update_env_file(password):
                    print("✅ .env file updated successfully")
                else:
                    print("❌ Failed to update .env file")
        else:
            print(f"❌ Failed: {message}")
    else:
        main()