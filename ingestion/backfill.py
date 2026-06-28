import boto3
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

def invoke_hour(hour_str):
    client = boto3.client('lambda', region_name='us-east-1')
    print(f"Triggering: {hour_str}")
    response = client.invoke(
        FunctionName='gh-archive-ingestion',
        InvocationType='RequestResponse',
        Payload=json.dumps({"target_hour": hour_str})
    )
    result = json.loads(response['Payload'].read())
    rows = result.get('rows_loaded', 0)
    print(f"  → {rows:,} rows loaded")
    return rows

def backfill(start_date: str, end_date: str):
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    hour_list = []
    current = start
    while current <= end:
        for hour in range(24):
            hour_list.append(f"{current.strftime('%Y-%m-%d')}-{hour}")
        current += timedelta(days=1)
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(invoke_hour, hour_list)

if __name__ == "__main__":
    backfill("2026-06-15", "2026-06-26")