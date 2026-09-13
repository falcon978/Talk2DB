import asyncio
import asyncpg
import pandas as pd
import datetime
import numpy as np

async def main():
    conn = await asyncpg.connect(
        user='postgres', password='password',
        database='targetdb', host='127.0.0.1', port=5432
    )
    
    tables = [
        'farmer', 'plot', 'crop_cycle', 
        'sensor_reading', 'advisory', 
        'field_agent', 'field_visit'
    ]
    
    for table in tables:
        print(f"Checking if {table} has data...")
        # Table name is hardcoded in the list above, safe from SQL injection
        count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
        if count > 0:
            print(f"Skipping {table}: Already contains {count} records.")
            continue
            
        csv_path = f'db/data/{table}.csv'
        print(f"Loading {table} from {csv_path}...")
        df = pd.read_csv(csv_path)
        
        for col in df.columns:
            if 'date' in col.lower() or 'time' in col.lower() or col.endswith('_on') or col.endswith('_at'):
                s = pd.to_datetime(df[col])
                if (table == 'farmer' and col == 'registered_on') or \
                   (table == 'crop_cycle' and col in ('sown_date', 'harvest_date')) or \
                   (table == 'field_agent' and col == 'joined_on'):
                    df[col] = [x.date() if pd.notnull(x) else None for x in s]
                else:
                    df[col] = [x.to_pydatetime() if pd.notnull(x) else None for x in s]
        
        # Replace NaN/NaT with None cleanly
        df = df.replace({np.nan: None})
        
        columns = list(df.columns)
        placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        
        records = [tuple(x) for x in df.to_numpy()]
        
        try:
            await conn.executemany(query, records)
            print(f"Successfully loaded {len(records)} records into {table}.")
            await conn.execute(f"SELECT setval('{table}_id_seq', (SELECT MAX(id) FROM {table}))")
        except Exception as e:
            print(f"Error loading {table}: {e}")
            break
        
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
