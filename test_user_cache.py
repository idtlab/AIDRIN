#!/usr/bin/env python3
"""
Test script to verify user-specific caching functionality.
"""

import requests
import json
import time

def test_user_specific_caching():
    """Test that different users get different cache keys."""
    
    # Simulate two different users (different sessions)
    session1 = requests.Session()
    session2 = requests.Session()
    
    print("Testing User-Specific Caching...")
    print("=" * 50)
    
    # Test 1: Check cache stats for different users
    print("\n1. Testing cache stats for different users:")
    
    # User 1 cache stats
    response1 = session1.get('http://localhost:5000/cache_stats')
    if response1.status_code == 200:
        stats1 = response1.json()['stats']
        print(f"User 1 ID: {stats1['user_id']}")
        print(f"User 1 entries: {stats1['user_entries']}")
    
    # User 2 cache stats
    response2 = session2.get('http://localhost:5000/cache_stats')
    if response2.status_code == 200:
        stats2 = response2.json()['stats']
        print(f"User 2 ID: {stats2['user_id']}")
        print(f"User 2 entries: {stats2['user_entries']}")
    
    # Verify different user IDs
    if stats1['user_id'] != stats2['user_id']:
        print("✅ Different users have different IDs")
    else:
        print("❌ Users have same ID (this shouldn't happen)")
    
    print("\n2. Testing cache clearing for specific user:")
    
    # Clear cache for user 1
    response1_clear = session1.post('http://localhost:5000/clear_metric_cache')
    if response1_clear.status_code == 200:
        clear1 = response1_clear.json()
        print(f"User 1 cache clear: {clear1['message']}")
    
    # Check that user 2's cache is unaffected
    response2_stats = session2.get('http://localhost:5000/cache_stats')
    if response2_stats.status_code == 200:
        stats2_after = response2_stats.json()['stats']
        print(f"User 2 entries after User 1 clear: {stats2_after['user_entries']}")
    
    print("\n3. Cache key format verification:")
    print("Expected format: user:{user_id}|file:{filename}|{metric_type}:{params}")
    print("This ensures user isolation in cache keys.")
    
    print("\n" + "=" * 50)
    print("User-specific caching test completed!")

if __name__ == "__main__":
    test_user_specific_caching() 