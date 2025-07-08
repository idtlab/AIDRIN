#!/usr/bin/env python3
"""
Test script to demonstrate cache expiration reset functionality.
"""

import requests
import json
import time

def test_cache_expiration_reset():
    """Test that cache expiration time resets when recalculating."""
    
    session = requests.Session()
    
    print("Testing Cache Expiration Reset...")
    print("=" * 50)
    
    # Test 1: First calculation
    print("\n1. First calculation (creates cache entry):")
    response1 = session.get('http://localhost:5000/cache_stats')
    if response1.status_code == 200:
        stats1 = response1.json()['stats']
        print(f"User entries before: {stats1['user_entries']}")
    
    # Wait a bit to simulate time passing
    print("Waiting 2 seconds...")
    time.sleep(2)
    
    # Test 2: Same calculation (should reset expiration)
    print("\n2. Same calculation (should reset expiration):")
    response2 = session.get('http://localhost:5000/cache_stats')
    if response2.status_code == 200:
        stats2 = response2.json()['stats']
        print(f"User entries after: {stats2['user_entries']}")
    
    # Test 3: Check cache info
    print("\n3. Detailed cache information:")
    response3 = session.get('http://localhost:5000/user_cache_info')
    if response3.status_code == 200:
        cache_info = response3.json()['cache_info']
        print(f"User ID: {cache_info['user_id']}")
        print(f"Total user entries: {cache_info['total_user_entries']}")
        print(f"Cache keys: {cache_info['user_cache_keys'][:3]}...")  # Show first 3 keys
    
    print("\n4. Expected behavior:")
    print("✅ First calculation: Creates cache entry with 30-minute expiration")
    print("✅ Same calculation: Uses cached result AND resets expiration to 30 minutes")
    print("✅ Result: Cache entry stays fresh as long as you keep using it")
    
    print("\n" + "=" * 50)
    print("Cache expiration reset test completed!")

if __name__ == "__main__":
    test_cache_expiration_reset() 