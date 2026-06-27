import boto3
import json
from datetime import datetime, timedelta

def backfill(start_date: str, end_date: str):
    """
    start_date, end_date: 'YYYY-MM-DD' 형식
    """
    client = boto3.client('lambda', region_name='us-east-1')
    
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    current = start
    while current <= end:
        for hour in range(24):
            hour_str = f"{current.strftime('%Y-%m-%d')}-{hour}"
            print(f"Triggering: {hour_str}")
            
            response = client.invoke(
                FunctionName='gh-archive-ingestion',
                InvocationType='RequestResponse',  # 동기 호출 — 완료 기다림
                Payload=json.dumps({"target_hour": hour_str})
            )
            
            result = json.loads(response['Payload'].read())
            print(f"  → {result.get('rows_loaded', 0):,} rows loaded")
        
        current += timedelta(days=1)

if __name__ == "__main__":
    backfill("2024-06-16", "2026-06-26")