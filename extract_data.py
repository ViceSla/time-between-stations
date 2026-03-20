import pandas as pd


def get_trips_between(file_path, stop_a, stop_b):
    chunks = []
    # Use usecols to save memory—we only need these 3 columns
    columns = ['trip_id', 'stop_id', 'stop_sequence']

    for chunk in pd.read_csv(file_path, chunksize=100000, usecols=columns, dtype=str):
        # 1. Keep only rows involving our two stops
        filtered = chunk[chunk['stop_id'].isin([stop_a, stop_b])].copy()
        
        # Convert sequence to numeric for comparison
        filtered['stop_sequence'] = pd.to_numeric(filtered['stop_sequence'])
        chunks.append(filtered)
        
    # Combine all filtered results
    df_filtered = pd.concat(chunks)

    # 2. Pivot the data so each trip has a row with stop_a and stop_b sequences
    # Index is trip_id, columns are the stop_ids, values are the sequences
    df_pivoted = df_filtered.pivot(index='trip_id', columns='stop_id', values='stop_sequence')

    # 3. Ensure both stops exist for the trip and that A comes before B
    # We dropna() to remove trips that only visited one of the two stations
    valid_trips = df_pivoted.dropna(subset=[stop_a, stop_b])
    result = valid_trips[valid_trips[stop_b] > valid_trips[stop_a]]

    return result.index.tolist()


with open("Moje Stanice.txt", "r") as f:
    data = f.read().split("\n")
    stanica1, stanica2 = data[0], data[1]

trips = get_trips_between("static_podatci/stop_times.txt", stanica1, stanica2)
with open("ids_to_check.txt", "w") as f:
    f.write(",".join(trips))
    f.close()