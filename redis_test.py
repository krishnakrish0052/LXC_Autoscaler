#!/usr/bin/env python3
"""
Redis connection test script
This simple script attempts to connect to Redis with different configurations
to help diagnose connection issues.
"""
import redis
import sys

def test_connection(host='localhost', port=6379, password=None, description=""):
    """Test Redis connection with given parameters"""
    try:
        print(f"\nTesting: {description}")
        print(f"Connection params: host={host}, port={port}, password={password}")
        
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
        print(f"✅ SUCCESS: PING response: {response}")
        
        # Test setting and getting a value
        client.setex("test_key", 10, "test_value")
        value = client.get("test_key")
        print(f"✅ SUCCESS: Set and get test value: {value}")
        
        return True
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        print(f"Exception type: {type(e).__name__}")
        return False

if __name__ == "__main__":
    print("Redis Connection Test Script")
    print("============================")
    
    # Get Redis connection parameters from command line
    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
    
    # Test with empty/no password
    no_pass = test_connection(host=host, port=port, password=None, 
                             description="No password")
    
    # Test with empty string password
    empty_pass = test_connection(host=host, port=port, password="", 
                                description="Empty string password")
    
    # Test with "default" password (commonly used in some Redis setups)
    default_pass = test_connection(host=host, port=port, password="default", 
                                  description="'default' password")
    
    # Print summary
    print("\nTest Summary")
    print("============")
    print(f"No password: {'✅ SUCCESS' if no_pass else '❌ FAILED'}")
    print(f"Empty string password: {'✅ SUCCESS' if empty_pass else '❌ FAILED'}")
    print(f"'default' password: {'✅ SUCCESS' if default_pass else '❌ FAILED'}")
    
    if not (no_pass or empty_pass or default_pass):
        print("\n⚠️ All connection attempts failed!")
        print("Your Redis server likely requires a specific password.")
        print("You might need to:")
        print("1. Check Redis configuration in /etc/redis/redis.conf")
        print("2. Run 'redis-cli' and try 'AUTH yourpassword'")
        print("3. Set the correct password in your .env file")
    else:
        print("\nAt least one connection method worked!")
        print("Update your application code to use the successful method.")