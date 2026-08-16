import re
import requests
import json
import os

print("Fetching latest Steam AppID index... (This may take a moment)")
try:
    # Using a reliable community endpoint instead of Steam's unstable live endpoint
    url = "https://githubusercontent.com"
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}, timeout=15)
    response.raise_for_status()
    steam_data = response.json()
    
    # Map AppID -> Game Name
    app_mapping = {str(app['appid']): app['name'] for app in steam_data['applist']['apps']}
except Exception as e:
    print(f"Error fetching Steam API data: {e}")
    exit(1)

if not os.path.exists('raw_licenses.txt'):
    print("Error: 'raw_licenses.txt' not found in this folder. Please create it first.")
    exit(1)

# Extract numbers from the licenses text file
with open('raw_licenses.txt', 'r') as f:
    text = f.read()

# Match patterns like "AppID 12345" or just find raw IDs listed in the licenses block
found_ids = set(re.findall(r'(?:AppID\s*|:\s*)(\d+)', text))

# Fallback: if it's a completely raw block of text, grab any sequences of digits
if not found_ids:
    found_ids = set(re.findall(r'\b\d{3,7}\b', text))

games_list = []
for app_id in found_ids:
    if app_id in app_mapping and app_mapping[app_id].strip():
        games_list.append(app_mapping[app_id])

# Sort the games alphabetically
games_list.sort()

# Save the final clear text file
with open('my_steam_games.txt', 'w') as f:
    for game in games_list:
        f.write(f"{game}\n")

print(f"\nSuccess! Found {len(games_list)} unique games.")
print("Your clean list has been exported to: my_steam_games.txt")
