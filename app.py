from flask import Flask, jsonify
import pandas as pd

app = Flask(__name__)

# The endpoint, when run locally is localhost:5000/cheapest_listings
@app.route('/cheapest_listings', methods=['GET'])
def cheapest_listings():
    csv_filename = "booking_listings.csv"
    try:
        df = pd.read_csv(csv_filename)
    except FileNotFoundError:
        print(f"Error: CSV file '{csv_filename}' not found.")
        return jsonify({"error": f"CSV file '{csv_filename}' not found. Please run the scraper first."}), 404
    except pd.errors.EmptyDataError:
        print(f"Error: CSV file '{csv_filename}' is empty.")
        return jsonify({"error": f"CSV file '{csv_filename}' is empty. No data to process."}), 400
    except Exception as e:
        print(f"Error reading CSV file '{csv_filename}': {e}")
        return jsonify({"error": f"Failed to read or process CSV file: {e}"}), 500

    if df.empty:
         return jsonify([])

    # Convert 'Cost (AUD)' column to numeric
    df['Cost_Numeric'] = pd.to_numeric(df['Cost (AUD)'], errors='coerce')

    # Sort by the numeric cost column (lowest first). NaN values will be placed last by default.
    df_sorted = df.sort_values(by="Cost_Numeric", ascending=True, na_position='last')
    df_top50 = df_sorted.head(50)
    df_top50 = df_top50.drop(columns=['Cost_Numeric'])

    # Convert NaN values (which might appear if cost conversion failed) to None for JSON compatibility
    df_top50 = df_top50.where(pd.notnull(df_top50), None)

    return jsonify(df_top50.to_dict(orient="records"))

if __name__ == '__main__':
    # Running on localhost:5000 by default
    app.run(debug=True)