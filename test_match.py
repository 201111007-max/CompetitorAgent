"""测试比赛数据获取"""
import sys
sys.path.insert(0, 'DotaHelperAgent')

from utils.api_client import OpenDotaClient

client = OpenDotaClient()
match_data = client._make_request('/matches/8893253595')

if match_data:
    print(f"Match ID: {match_data.get('match_id')}")
    print(f"Duration: {match_data.get('duration')}s")
    print(f"Duration (minutes): {match_data.get('duration') / 60:.1f}")
    print(f"Radiant Win: {match_data.get('radiant_win')}")
    print(f"Radiant Score: {match_data.get('radiant_score')}")
    print(f"Dire Score: {match_data.get('dire_score')}")
    print(f"Start Time: {match_data.get('start_time')}")
else:
    print("Failed to fetch match data")
