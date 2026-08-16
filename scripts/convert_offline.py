import re
import os
import sys

# Ensure parent directory is in path to import vnpatchmanager
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnpatchmanager.steam_scanner import SteamScanner

# 1. Detect your raw console dump file
input_file = 'raw_licenses.txt'
if not os.path.exists(input_file):
    print(f"Error: {input_file} not found in this folder!")
    exit(1)

# 2. Extract every single number (AppIDs) from the console dump
with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
    raw_content = f.read()

# Grab any string of numbers from 3 to 7 digits long
found_ids = set(re.findall(r'\b\d{3,7}\b', raw_content))
if not found_ids:
    print("Error: Could not extract any AppIDs from raw_licenses.txt.")
    exit(1)

print(f"Extracted {len(found_ids)} AppIDs from your console dump. Translating offline...")

# 3. Use the modular SteamScanner to fetch games metadata
owned_games = SteamScanner.get_owned_games()

# 4. Cross-reference the lists
final_games = []
for app_id in found_ids:
    if app_id in owned_games:
        final_games.append(owned_games[app_id]["name"])

# 5. Sort and export to file
if final_games:
    final_games = sorted(list(set(final_games)))
    with open('my_steam_games.txt', 'w', encoding='utf-8') as out_f:
        for game in final_games:
            out_f.write(f"{game}\n")
    print(f"Success! Translated and exported {len(final_games)} games to my_steam_games.txt")
else:
    print("\nCould not resolve the text names natively.")
    print("Please paste the first 5 lines of your 'raw_licenses.txt' so I can fix the extractor pattern!")
